import httpx
import pytest

from agent import api


def test_each_function_calls_its_backend_operation(client):
    assert len(api.list_claims()) == 25
    assert api.get_claim("CLM-1001")["customer_name"] == "Maya Patel"
    assert api.get_policy("POL-2001")["plan"] == "premium"
    assert [c["claim_id"] for c in api.get_claim_history("CUS-3001")] == ["CLM-0412"]
    assert set(api.get_instructions()) == {"queue", "claim"}
    assert len(api.list_sections("claims_manual")) == 14
    assert api.read_section("claims_manual", 9)["title"] == "Repeat claims"

    assert api.start_claim("CLM-1001", "t-1")["status"] == "in_progress"
    assert api.record_step("CLM-1001", "message", "Hi")["kind"] == "message"
    decided = api.record_decision("CLM-1001", "approve", 420.0, "Section 3", "Ok.")
    assert decided["status"] == "decided"
    assert api.pay_claim("CLM-1001", 420.0)["amount"] == 420.0

    api.start_claim("CLM-1002", "t-2")
    assert api.fail_claim("CLM-1002", "Timed out")["status"] == "waiting"

    assert api.start_run("run-1", 5)["cap"] == 5
    todos = [{"content": "CLM-1003", "status": "to_do"}]
    assert api.write_todos("run-1", todos)["todos"] == todos
    assert api.finish_run("run-1", "Worked 1 claim.")["summary"] == "Worked 1 claim."


def test_a_refusal_raises_with_its_status_and_reason(client):
    with pytest.raises(api.ApiError, match="404: Claim CLM-9999 not found") as error:
        api.get_claim("CLM-9999")
    assert error.value.status == 404
    assert error.value.reason == "Claim CLM-9999 not found"


@pytest.mark.parametrize(
    "answer",
    [httpx.ConnectError("Connection refused"), httpx.Response(500, text="Oops")],
)
def test_a_lost_connection_or_a_server_error_can_be_tried_again(monkeypatch, answer):
    def handler(request):
        if isinstance(answer, Exception):
            raise answer
        return answer

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(
        api,
        "_client",
        lambda: httpx.Client(base_url=api.backend_url(), transport=transport),
    )
    with pytest.raises(api.ApiUnavailable):
        api.list_claims()


def test_the_backend_address_follows_the_dashboards_setting(monkeypatch):
    monkeypatch.setenv("UNDERCOVER_API", "http://127.0.0.1:8002")
    assert api.backend_url() == "http://127.0.0.1:8002"
    monkeypatch.delenv("UNDERCOVER_API")
    assert api.backend_url() == "http://127.0.0.1:8000"
