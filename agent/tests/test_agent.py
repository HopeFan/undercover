import pytest
from langchain_core.messages import AIMessage, SystemMessage, ToolMessage

from agent import __main__ as cli
from agent import api, harness
from agent.tests.stubs import StubModel, call, script


def test_run_approves_and_pays_within_the_limit(client):
    stub = script(
        "approve",
        420.0,
        call("pay_claim", text="Paying now.", amount=420.0),
    )
    assert harness.run_claim_agent("CLM-1001", "thread-1", stub) == "Decision: approve."

    claim = client.get("/api/claims/CLM-1001").json()
    assert claim["status"] == "decided"
    assert claim["thread_id"] == "thread-1"
    assert claim["decision"]["payout"] == 420.0
    assert claim["payment"]["amount"] == 420.0

    steps = client.get("/api/claims/CLM-1001/steps").json()
    assert [s["kind"] for s in steps] == [
        *(["tool_call", "tool_result"] * 4),
        "message",
        "tool_call",
        "tool_result",
        "message",
    ]
    assert steps[0]["content"] == "get_claim()"
    assert steps[1]["content"].startswith('get_claim: {"claim_id": "CLM-1001"')
    assert steps[8]["content"] == "Paying now."
    assert steps[9]["content"] == "pay_claim(amount=420.0)"
    assert steps[-1]["content"] == "Decision: approve."
    assert {s["thread_id"] for s in steps} == {"thread-1"}


def test_run_uses_the_instructions_from_the_backend(client):
    stub = script("refer", 0)
    harness.run_claim_agent("CLM-1003", "thread-1", stub)
    system = stub.prompts[0][0]
    assert isinstance(system, SystemMessage)
    assert system.content == client.get("/api/instructions").json()["claim"]


def test_payment_over_the_limit_is_refused(client):
    stub = script(
        "approve",
        1350.0,
        call("pay_claim", amount=1350.0),
    )
    harness.run_claim_agent("CLM-1002", "thread-2", stub)

    refusal = stub.prompts[-1][-1]
    assert isinstance(refusal, ToolMessage)
    assert "needs a handler's sign-off" in refusal.text
    assert refusal.text.startswith("Refused with status 403")
    assert refusal.status == "error"

    claim = client.get("/api/claims/CLM-1002").json()
    assert claim["status"] == "waiting_for_sign_off"
    assert claim["payment"] is None


@pytest.mark.parametrize("decision", ["decline", "refer"])
def test_run_declines_and_refers(client, decision):
    harness.run_claim_agent("CLM-1003", "thread-3", script(decision, 0))
    claim = client.get("/api/claims/CLM-1003").json()
    assert claim["status"] == "decided"
    assert claim["decision"]["decision"] == decision
    assert claim["payment"] is None


def test_run_records_the_sections_it_reads(client):
    stub = StubModel(
        messages=iter(
            [
                call("list_sections", document="claims_manual"),
                call("read_section", document="claims_manual", section=9),
                call("read_section", document="claims_manual", section=99),
                call(
                    "record_decision",
                    decision="refer",
                    payout=0,
                    section="Claims manual, section 9, Repeat claims",
                    reason="This is the customer's third claim in 12 months.",
                ),
                AIMessage(content="Referred, $0.00"),
            ]
        )
    )
    harness.run_claim_agent("CLM-1003", "thread-5", stub)

    steps = client.get("/api/claims/CLM-1003/steps").json()
    reads = [s for s in steps if s["kind"] == "read"]
    assert len(reads) == 1
    heading, _, text = reads[0]["content"].partition("\n\n")
    assert heading == "Claims manual, section 9: Repeat claims"
    assert text.startswith("Before deciding any claim")
    assert steps[1]["content"].startswith('list_sections: [{"section": 1')
    refused = next(
        m
        for m in stub.prompts[-1]
        if isinstance(m, ToolMessage) and m.status == "error"
    )
    assert refused.name == "read_section"
    refusal = steps[5]
    assert refusal["kind"] == "tool_result"
    assert refusal["content"].startswith("read_section: Refused with status 404")
    assert client.get("/api/claims/CLM-1003").json()["status"] == "decided"


def test_an_empty_history_reaches_the_model_as_an_empty_list(client):
    stub = script("refer", 0)
    harness.run_claim_agent("CLM-1003", "thread-6", stub)
    history = next(
        m
        for m in stub.prompts[-1]
        if isinstance(m, ToolMessage) and m.name == "get_claim_history"
    )
    assert history.text == "[]"


def test_run_needs_a_waiting_claim():
    harness.run_claim_agent("CLM-1003", "thread-3", script("refer", 0))
    with pytest.raises(api.ApiError, match="409: Claim CLM-1003 is not waiting"):
        harness.run_claim_agent("CLM-1003", "thread-4", StubModel(messages=iter([])))


def test_command_line(monkeypatch, capsys):
    monkeypatch.setattr(cli, "work_claim", lambda claim_id: f"{claim_id}  refer  $0.00")
    cli.main(["CLM-1001"])
    assert capsys.readouterr().out == "CLM-1001  refer  $0.00\n"


def test_model_name(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.delenv("MODEL_NAME", raising=False)
    default = harness.model()
    assert default.model_name == "deepseek/deepseek-v4.1-flash"
    assert default.reasoning_effort == "low"
    assert default.request_timeout == harness.MODEL_TIMEOUT
    monkeypatch.setenv("MODEL_NAME", "openrouter/free")
    assert harness.model().model_name == "openrouter/free"
    assert harness.model().reasoning_effort is None
