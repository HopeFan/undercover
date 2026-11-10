import sqlite3
from contextlib import closing

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from agent import __main__ as cli
from agent import main, queue
from agent.tests.test_agent import StubModel, call
from agent.tests.test_failures import UNAVAILABLE


@pytest.fixture
def three_waiting(database):
    """Leave only CLM-1001, CLM-1002 and CLM-1003 waiting in the queue."""
    with closing(sqlite3.connect(database)) as db, db:
        db.execute(
            "UPDATE claims SET status = 'decided'"
            " WHERE claim_id NOT IN ('CLM-1001', 'CLM-1002', 'CLM-1003')"
        )


@pytest.fixture
def outcomes(monkeypatch):
    """Stand in for the claim agent, deciding each claim as scripted or failing."""
    scripted: dict[str, list[str]] = {}

    def run(claim_id, thread_id, llm=None):
        main.call_backend(
            "POST", f"/api/claims/{claim_id}/start", {"thread_id": thread_id}
        )
        outcome = scripted[claim_id].pop(0)
        if outcome == "fail":
            raise UNAVAILABLE
        main.call_backend(
            "POST",
            f"/api/claims/{claim_id}/decision",
            {
                "decision": outcome,
                "payout": 420.0 if outcome == "approve" else 0,
                "section": "Section 3, Trip Delay",
                "reason": "Covered.",
            },
        )
        return "Done."

    monkeypatch.setattr(main, "run", run)
    return scripted


def queue_model(*replies):
    return StubModel(messages=iter(replies))


def plan(*statuses):
    return [
        {"content": f"CLM-100{n}", "status": status}
        for n, status in enumerate(statuses, start=1)
    ]


def humans(stub):
    return [m.text for m in stub.prompts[-1] if isinstance(m, HumanMessage)]


def status(client, claim_id):
    return client.get(f"/api/claims/{claim_id}").json()["status"]


def test_the_queue_agents_tools(client):
    operations = {
        operation["operationId"]
        for path in client.get("/openapi.json").json()["paths"].values()
        for operation in path.values()
    }
    names = [t.name for t in queue.queue_tools("run-1", 5, [], None)]
    assert names == ["list_claims", "write_todos", "work_claim"]
    assert {"list_claims", "write_todos"} <= operations


def test_the_to_do_list_is_stored_as_the_agent_works(
    monkeypatch, capsys, client, three_waiting, outcomes
):
    outcomes.update({"CLM-1001": ["approve"], "CLM-1002": ["refer"]})
    seen = []
    real_work_claim = main.work_claim

    def work_claim(claim_id, llm=None):
        seen.append(client.get("/api/runs/current").json()["todos"])
        return real_work_claim(claim_id, llm)

    monkeypatch.setattr(main, "work_claim", work_claim)
    stub = queue_model(
        call("list_claims"),
        call("write_todos", todos=plan("to_do", "to_do")),
        call("write_todos", todos=plan("in_progress", "to_do")),
        call("work_claim", claim_id="CLM-1001"),
        call("write_todos", todos=plan("done", "in_progress")),
        call("work_claim", claim_id="CLM-1002"),
        call("write_todos", todos=plan("done", "done")),
        AIMessage(content="Worked 2 claims: 1 approve and 1 refer."),
    )
    queue.work_queue(2, stub)

    assert seen == [plan("in_progress", "to_do"), plan("done", "in_progress")]
    run = client.get("/api/runs/current").json()
    assert run["cap"] == 2
    assert run["todos"] == plan("done", "done")
    assert run["summary"] == "Worked 2 claims: 1 approve and 1 refer."
    assert run["finished_at"] is not None
    assert capsys.readouterr().out.splitlines() == [
        "CLM-1001  approve  $420.00",
        "CLM-1002  refer  $0.00",
        "",
        "Worked 2 claims: 1 approve and 1 refer.",
    ]
    system = stub.prompts[0][0]
    assert isinstance(system, SystemMessage)
    assert system.content == client.get("/api/instructions").json()["queue"]
    assert humans(stub) == ["Work the waiting claims in the queue, up to 2."]


def test_a_run_never_starts_more_claims_than_its_cap(
    capsys, client, three_waiting, outcomes
):
    outcomes.update({"CLM-1001": ["approve"], "CLM-1002": ["approve"]})
    stub = queue_model(
        call("work_claim", claim_id="CLM-1001"),
        call("work_claim", claim_id="CLM-1002"),
        call("work_claim", claim_id="CLM-1003"),
        AIMessage(content="Worked 2 claims."),
    )
    queue.work_queue(2, stub)
    assert capsys.readouterr().out.splitlines()[2] == (
        "Refused: this run is capped at 2 claims."
    )
    assert status(client, "CLM-1003") == "waiting"


def test_a_failed_claim_goes_back_in_the_queue_and_the_run_carries_on(
    capsys, client, three_waiting, outcomes
):
    outcomes.update(
        {
            "CLM-1001": ["approve"],
            "CLM-1002": ["fail", "refer"],
            "CLM-1003": ["decline"],
        }
    )
    stub = queue_model(
        call("work_claim", claim_id="CLM-1001"),
        call("work_claim", claim_id="CLM-1002"),
        call("work_claim", claim_id="CLM-1003"),
        call("work_claim", claim_id="CLM-1002"),
        AIMessage(content="Worked 3 claims."),
    )
    queue.work_queue(None, stub)
    assert capsys.readouterr().out.splitlines() == [
        "CLM-1001  approve  $420.00",
        "CLM-1002  failed: The model is unavailable. Back in the queue.",
        "CLM-1003  decline  $0.00",
        "CLM-1002  refer  $0.00",
        "",
        "Worked 3 claims.",
    ]
    assert {status(client, f"CLM-100{n}") for n in (1, 2, 3)} == {"decided"}
    assert client.get("/api/runs/current").json()["cap"] == 3


def test_a_claim_that_fails_twice_is_left_for_a_handler(
    capsys, client, three_waiting, outcomes
):
    outcomes.update({"CLM-1001": ["fail", "fail"]})
    stub = queue_model(
        call("write_todos", todos=plan("to_do")),
        call("work_claim", claim_id="CLM-1001"),
        call("work_claim", claim_id="CLM-1001"),
        call("write_todos", todos=plan("left_for_handler")),
        AIMessage(content="CLM-1001 was left for a handler."),
    )
    queue.work_queue(1, stub)
    assert capsys.readouterr().out.splitlines()[1] == (
        "CLM-1001  failed: The model is unavailable. Left for a handler."
    )
    assert status(client, "CLM-1001") == "left_for_handler"
    run = client.get("/api/runs/current").json()
    assert run["todos"] == plan("left_for_handler")
    assert len(humans(stub)) == 1


def test_the_agent_is_reminded_of_waiting_claims_within_its_cap(
    client, three_waiting, outcomes
):
    outcomes.update({"CLM-1001": ["approve"], "CLM-1002": ["approve"]})
    stub = queue_model(
        call("work_claim", claim_id="CLM-1001"),
        AIMessage(content="Done."),
        call("work_claim", claim_id="CLM-1002"),
        AIMessage(content="Worked 2 claims."),
    )
    queue.work_queue(2, stub)
    reminder = humans(stub)[1]
    assert "CLM-1002" in reminder
    assert "CLM-1003" not in reminder
    assert status(client, "CLM-1002") == "decided"
    assert status(client, "CLM-1003") == "waiting"
    assert client.get("/api/runs/current").json()["summary"] == "Worked 2 claims."


def test_a_claim_back_in_the_queue_is_a_missed_claim(client, three_waiting, outcomes):
    outcomes.update({"CLM-1001": ["fail", "approve"]})
    stub = queue_model(
        call("work_claim", claim_id="CLM-1001"),
        AIMessage(content="Done."),
        call("work_claim", claim_id="CLM-1001"),
        AIMessage(content="Worked 1 claim."),
    )
    queue.work_queue(1, stub)
    assert "CLM-1001" in humans(stub)[1]
    assert status(client, "CLM-1001") == "decided"


def test_after_two_reminders_the_run_finishes_anyway(client, three_waiting):
    stub = queue_model(
        AIMessage(content="Nothing to do."),
        AIMessage(content="Still nothing."),
        AIMessage(content="I'm done."),
    )
    queue.work_queue(2, stub)
    assert len(humans(stub)) == 3
    assert client.get("/api/runs/current").json()["summary"] == "I'm done."
    assert status(client, "CLM-1001") == "waiting"


def test_a_failure_of_the_queue_agent_finishes_the_run_and_says_why(
    capsys, client, three_waiting
):
    queue.work_queue(2, queue_model(*[UNAVAILABLE] * 4))
    summary = "The run stopped: The model is unavailable"
    assert client.get("/api/runs/current").json()["summary"] == summary
    assert capsys.readouterr().out.splitlines()[-1] == summary


def test_work_claim_refuses_claims_that_are_not_waiting_or_unknown(
    capsys, client, three_waiting, outcomes
):
    outcomes.update({"CLM-1001": ["approve"]})
    stub = queue_model(
        call("work_claim", claim_id="CLM-1004"),
        call("work_claim", claim_id="CLM-9999"),
        call("work_claim", claim_id="CLM-1001"),
        AIMessage(content="Worked 1 claim."),
    )
    queue.work_queue(1, stub)
    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == "Refused: CLM-1004 is not waiting, it is decided."
    assert lines[1].startswith("Refused with status 404")
    assert lines[2] == "CLM-1001  approve  $420.00"


def test_nothing_waiting(capsys, client, database):
    with closing(sqlite3.connect(database)) as db, db:
        db.execute("UPDATE claims SET status = 'decided'")
    queue.work_queue(5, queue_model())
    assert capsys.readouterr().out == "No claims are waiting.\n"
    assert client.get("/api/runs/current").json() is None


def test_command_line_cap(monkeypatch):
    caps = []
    monkeypatch.setattr(cli, "work_queue", caps.append)
    cli.main(["--cap", "5"])
    cli.main([])
    assert caps == [5, None]
