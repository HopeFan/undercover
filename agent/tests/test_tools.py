from langchain_core.messages import AIMessage
from langchain_core.utils.function_calling import convert_to_openai_tool

from agent import main
from agent.tests.test_agent import StubModel, call
from agent.tools import CLAIM_TOOLS, QUEUE_TOOLS


def test_the_tools_are_named_after_backend_operations(client):
    operations = {
        operation["operationId"]
        for path in client.get("/openapi.json").json()["paths"].values()
        for operation in path.values()
    }
    claim_tools = [t.name for t in CLAIM_TOOLS]
    assert claim_tools == [
        "get_claim",
        "get_policy",
        "get_claim_history",
        "list_sections",
        "read_section",
        "record_decision",
        "pay_claim",
    ]
    queue_tools = [t.name for t in QUEUE_TOOLS]
    assert queue_tools == ["list_claims", "write_todos", "work_claim"]
    assert set(claim_tools + ["list_claims", "write_todos"]) <= operations


def test_the_claim_agent_cannot_name_a_claim_policy_or_customer():
    for tool in CLAIM_TOOLS:
        seen_by_model = convert_to_openai_tool(tool)["function"]["parameters"]
        arguments = set(seen_by_model["properties"])
        assert not {"claim_id", "policy_id", "customer_id"} & arguments, tool.name


def test_the_claim_agent_works_only_the_claim_in_its_context(client):
    stub = StubModel(
        messages=iter(
            [
                call(
                    "record_decision",
                    claim_id="CLM-1002",
                    decision="approve",
                    payout=420.0,
                    section="Section 3, Trip Delay",
                    reason="The delay was covered.",
                ),
                call("pay_claim", claim_id="CLM-1002", amount=420.0),
                AIMessage(content="Approved, $420.00"),
            ]
        )
    )
    assert main.work_claim("CLM-1001", stub) == "CLM-1001  approve  $420.00"
    assert client.get("/api/claims/CLM-1001").json()["payment"]["amount"] == 420.0
    assert client.get("/api/claims/CLM-1002").json()["status"] == "waiting"
