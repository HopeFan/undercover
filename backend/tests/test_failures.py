import pytest

from backend.tests.test_workflow import decide, start


def fail(client, claim_id, error="The model timed out"):
    return client.post(f"/api/claims/{claim_id}/failure", json={"error": error})


def test_a_failed_claim_goes_back_in_the_queue(client):
    start(client, "CLM-1001")
    response = fail(client, "CLM-1001")
    assert response.status_code == 200
    assert response.json()["status"] == "waiting"
    steps = client.get("/api/claims/CLM-1001/steps").json()
    assert [(s["kind"], s["content"]) for s in steps] == [
        ("error", "The model timed out")
    ]


def test_a_claim_that_fails_twice_is_left_for_a_handler(client):
    start(client, "CLM-1001")
    fail(client, "CLM-1001")
    start(client, "CLM-1001")
    response = fail(client, "CLM-1001", "The model is unavailable")
    assert response.json()["status"] == "left_for_handler"
    assert start(client, "CLM-1001").status_code == 409
    summary = client.get("/api/claims").json()[0]
    assert summary["status"] == "left_for_handler"


def test_only_a_claim_in_progress_can_fail(client):
    assert fail(client, "CLM-1001").status_code == 409
    start(client, "CLM-1002")
    decide(client, "CLM-1002", "approve", 1350.0)
    start(client, "CLM-1003")
    decide(client, "CLM-1003", "decline", 0)
    for claim_id, status in (
        ("CLM-1002", "waiting_for_sign_off"),
        ("CLM-1003", "decided"),
    ):
        response = fail(client, claim_id)
        assert response.status_code == 409
        assert response.json()["detail"] == f"Claim {claim_id} is not in progress"
        assert client.get(f"/api/claims/{claim_id}").json()["status"] == status


@pytest.mark.parametrize(
    ("claim_id", "error", "status_code"),
    [("CLM-9999", "x", 404), ("CLM-1001", "", 422)],
)
def test_failure_needs_a_known_claim_and_an_error(client, claim_id, error, status_code):
    start(client, "CLM-1001")
    assert fail(client, claim_id, error).status_code == status_code
