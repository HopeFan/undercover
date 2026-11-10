import pytest

from backend.tests.test_failures import fail
from backend.tests.test_workflow import start

TODOS = [
    {"content": "Work CLM-1001", "status": "done"},
    {"content": "Work CLM-1002", "status": "in_progress"},
    {"content": "Work CLM-1003", "status": "to_do"},
    {"content": "Work CLM-1004", "status": "left_for_handler"},
]


def start_run(client, run_id="run-1", cap=5):
    return client.post("/api/runs", json={"run_id": run_id, "cap": cap})


def test_start_run(client):
    response = start_run(client)
    assert response.status_code == 200
    run = response.json()
    assert run["run_id"] == "run-1"
    assert run["cap"] == 5
    assert run["todos"] == []
    assert run["finished_at"] is None
    assert run["summary"] is None
    assert start_run(client).status_code == 409


def test_starting_a_run_fails_claims_a_stopped_run_left_in_progress(client):
    start(client, "CLM-1001")
    start(client, "CLM-1002")
    fail(client, "CLM-1002")
    start(client, "CLM-1002")
    start_run(client)
    assert client.get("/api/claims/CLM-1001").json()["status"] == "waiting"
    assert client.get("/api/claims/CLM-1002").json()["status"] == "left_for_handler"
    steps = client.get("/api/claims/CLM-1001/steps").json()
    assert [(s["kind"], s["content"]) for s in steps] == [
        ("error", "The run working this claim was stopped")
    ]


def test_write_todos(client):
    start_run(client)
    response = client.put("/api/runs/run-1/todos", json={"todos": TODOS})
    assert response.json()["todos"] == TODOS
    response = client.put("/api/runs/run-1/todos", json={"todos": TODOS[:1]})
    assert response.json()["todos"] == TODOS[:1]


@pytest.mark.parametrize(
    "todo",
    [
        {"content": "Work CLM-1001", "status": "pending"},
        {"content": "", "status": "done"},
    ],
)
def test_todos_need_a_known_status_and_content(client, todo):
    start_run(client)
    response = client.put("/api/runs/run-1/todos", json={"todos": [todo]})
    assert response.status_code == 422


def test_unknown_runs(client):
    assert client.put("/api/runs/run-9/todos", json={"todos": []}).status_code == 404
    response = client.post("/api/runs/run-9/finish", json={"summary": "Done."})
    assert response.status_code == 404


def test_finish_run(client):
    start_run(client)
    run = client.post("/api/runs/run-1/finish", json={"summary": "Worked 5."}).json()
    assert run["summary"] == "Worked 5."
    assert run["finished_at"] is not None


def test_get_current_run(client):
    assert client.get("/api/runs/current").json() is None
    start_run(client, "run-1")
    start_run(client, "run-2", cap=2)
    client.put("/api/runs/run-2/todos", json={"todos": TODOS})
    run = client.get("/api/runs/current").json()
    assert run["run_id"] == "run-2"
    assert run["cap"] == 2
    assert run["todos"] == TODOS
