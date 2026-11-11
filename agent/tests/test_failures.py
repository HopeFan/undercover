from collections import Counter

from langchain_core.messages import AIMessage

from agent import api, harness
from agent.tests.stubs import UNAVAILABLE, StubModel, call, script


def broken(*before):
    """A stub that works through its script, then fails on every retry."""
    return StubModel(messages=iter([*before, *[UNAVAILABLE] * 4]))


def approval_replies(*extra):
    return [
        call("get_claim"),
        call(
            "record_decision",
            decision="approve",
            payout=420.0,
            section="Section 3, Trip Delay",
            reason="The delay was covered.",
        ),
        *extra,
        AIMessage(content="Approved, $420.00"),
    ]


def approval(*extra):
    return StubModel(messages=iter(approval_replies(*extra)))


def pay():
    return call("pay_claim", amount=420.0)


def test_a_failed_claim_goes_back_in_the_queue_and_is_tried_again(client):
    line = harness.work_claim("CLM-1001", broken(call("get_claim")))
    assert line == "CLM-1001  failed: The model is unavailable. Back in the queue."
    assert client.get("/api/claims/CLM-1001").json()["status"] == "waiting"

    assert (
        harness.work_claim("CLM-1001", approval(pay())) == "CLM-1001  approve  $420.00"
    )
    claim = client.get("/api/claims/CLM-1001").json()
    assert claim["status"] == "decided"
    assert claim["payment"]["amount"] == 420.0

    steps = client.get("/api/claims/CLM-1001/steps").json()
    first, second = steps[0]["thread_id"], steps[-1]["thread_id"]
    assert first != second
    error = next(i for i, s in enumerate(steps) if s["kind"] == "error")
    assert steps[error]["content"] == "The model is unavailable"
    assert {s["thread_id"] for s in steps[: error + 1]} == {first}
    assert {s["thread_id"] for s in steps[error + 1 :]} == {second}


def test_a_claim_that_fails_twice_is_left_for_a_handler(client):
    harness.work_claim("CLM-1001", broken())
    line = harness.work_claim("CLM-1001", broken())
    assert line == "CLM-1001  failed: The model is unavailable. Left for a handler."
    assert client.get("/api/claims/CLM-1001").json()["status"] == "left_for_handler"

    line = harness.work_claim("CLM-1001", approval())
    assert line == "CLM-1001  not started: 409: Claim CLM-1001 is not waiting"
    assert client.get("/api/claims/CLM-1001").json()["status"] == "left_for_handler"


def test_a_model_call_that_fails_once_is_retried(client):
    stub = StubModel(messages=iter([UNAVAILABLE, *approval_replies(pay())]))
    assert harness.work_claim("CLM-1001", stub) == "CLM-1001  approve  $420.00"
    steps = client.get("/api/claims/CLM-1001/steps").json()
    assert "error" not in {s["kind"] for s in steps}


def test_a_claim_agent_going_in_circles_is_stopped(client):
    stub = StubModel(messages=iter([call("get_claim")] * 40))
    line = harness.work_claim("CLM-1001", stub)
    assert line.startswith("CLM-1001  failed: ")
    assert "limit" in line
    assert line.endswith("Back in the queue.")
    assert len(stub.prompts) == harness.CLAIM_MODEL_CALLS


def test_a_failure_after_the_decision_never_decides_or_pays_twice(client):
    line = harness.work_claim("CLM-1001", approval(*[UNAVAILABLE] * 4))
    assert line == "CLM-1001  approve  $420.00"
    claim = client.get("/api/claims/CLM-1001").json()
    assert claim["status"] == "decided"
    assert claim["decision"]["payout"] == 420.0
    assert claim["payment"]["amount"] == 420.0
    steps = client.get("/api/claims/CLM-1001/steps").json()
    assert (steps[-1]["kind"], steps[-1]["content"]) == (
        "error",
        "The model is unavailable",
    )

    line = harness.work_claim("CLM-1001", approval(pay()))
    assert line == "CLM-1001  not started: 409: Claim CLM-1001 is not waiting"
    assert client.get("/api/claims/CLM-1001").json()["payment"] == claim["payment"]


def test_finishing_without_a_decision_counts_as_a_failure(client):
    stub = StubModel(
        messages=iter([call("get_claim"), AIMessage(content="I'm not sure.")])
    )
    line = harness.work_claim("CLM-1001", stub)
    assert line == (
        "CLM-1001  failed: The agent finished without recording a decision."
        " Back in the queue."
    )


def test_an_approval_over_the_limit_waits_for_sign_off(client):
    stub = script(
        "approve",
        1350.0,
        call("pay_claim", amount=1350.0),
    )
    line = harness.work_claim("CLM-1002", stub)
    assert line == "CLM-1002  approve  $1,350.00  waiting for sign-off"
    assert client.get("/api/claims/CLM-1002").json()["payment"] is None


def test_a_refusal_is_not_retried_and_a_lost_connection_is(monkeypatch, client):
    calls = Counter()
    lost = iter([api.ApiUnavailable("Connection refused")] * 2)
    real_call = api._call

    def flaky_call(method, path, body=None):
        calls[path] += 1
        if path == "/api/policies/POL-2002" and (error := next(lost, None)):
            raise error
        return real_call(method, path, body)

    monkeypatch.setattr(api, "_call", flaky_call)
    stub = script(
        "approve",
        1350.0,
        call("pay_claim", amount=1350.0),
    )
    line = harness.work_claim("CLM-1002", stub)
    assert line == "CLM-1002  approve  $1,350.00  waiting for sign-off"
    assert calls["/api/policies/POL-2002"] == 3
    assert calls["/api/claims/CLM-1002/payment"] == 1


def test_an_error_that_is_not_a_refusal_stops_the_attempt(monkeypatch, client):
    real_call = api._call

    def down_for_policies(method, path, body=None):
        if path.startswith("/api/policies/"):
            raise api.ApiUnavailable("Connection refused")
        return real_call(method, path, body)

    monkeypatch.setattr(api, "_call", down_for_policies)
    stub = StubModel(messages=iter([call("get_policy"), *approval_replies()]))
    line = harness.work_claim("CLM-1001", stub)
    assert line == "CLM-1001  failed: Connection refused. Back in the queue."
