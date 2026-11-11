"""The UnderCover backend's API: its address and one function per operation."""

import os
from collections.abc import Mapping, Sequence
from typing import Any

import httpx

DEFAULT_BACKEND_URL = "http://127.0.0.1:8000"


class ApiError(Exception):
    """The backend refused a request, with its status and reason."""

    def __init__(self, status: int, reason: Any) -> None:
        super().__init__(f"{status}: {reason}")
        self.status = status
        self.reason = reason


class ApiUnavailable(Exception):
    """The backend could not be reached or failed, so the request can be tried again."""


def backend_url() -> str:
    """Return the backend's address: UNDERCOVER_API, which the dashboard reads too."""
    return os.getenv("UNDERCOVER_API", DEFAULT_BACKEND_URL)


def _client() -> httpx.Client:
    """Return a client for the backend."""
    return httpx.Client(base_url=backend_url(), timeout=30)


def _call(method: str, path: str, body: dict[str, Any] | None = None) -> Any:
    """Send one request and return its JSON, raising if it fails or is refused."""
    try:
        with _client() as http:
            response = http.request(method, path, json=body)
    except httpx.TransportError as error:
        raise ApiUnavailable(str(error) or type(error).__name__) from error
    if response.is_server_error:
        raise ApiUnavailable(f"The backend failed with status {response.status_code}")
    if response.is_error:
        raise ApiError(response.status_code, response.json()["detail"])
    return response.json()


def list_claims() -> list[dict[str, Any]]:
    """List every claim in the queue, in id order."""
    return _call("GET", "/api/claims")


def get_claim(claim_id: str) -> dict[str, Any]:
    """Get one claim in full: the story, the items claimed and the documents."""
    return _call("GET", f"/api/claims/{claim_id}")


def get_policy(policy_id: str) -> dict[str, Any]:
    """Get a policy: the plan, add-ons, purchase date, trip and travelers."""
    return _call("GET", f"/api/policies/{policy_id}")


def get_claim_history(customer_id: str) -> list[dict[str, Any]]:
    """Get a customer's earlier claims, with the outcome and the amount paid."""
    return _call("GET", f"/api/customers/{customer_id}/claims")


def get_instructions() -> dict[str, str]:
    """Get the agent's instructions for running the queue and for working a claim."""
    return _call("GET", "/api/instructions")


def list_sections(document: str) -> list[dict[str, Any]]:
    """List the numbered sections of the policy wording or the claims manual."""
    return _call("GET", f"/api/documents/{document}/sections")


def read_section(document: str, section: int) -> dict[str, Any]:
    """Read one numbered section of the policy wording or the claims manual."""
    return _call("GET", f"/api/documents/{document}/sections/{section}")


def start_claim(claim_id: str, thread_id: str) -> dict[str, Any]:
    """Start work on a waiting claim, which moves it to in progress."""
    return _call("POST", f"/api/claims/{claim_id}/start", {"thread_id": thread_id})


def record_step(claim_id: str, kind: str, content: str) -> dict[str, Any]:
    """Record one step of the agent's work on a claim."""
    return _call(
        "POST", f"/api/claims/{claim_id}/steps", {"kind": kind, "content": content}
    )


def record_decision(
    claim_id: str, decision: str, payout: float, section: str, reason: str
) -> dict[str, Any]:
    """Record the decision on a claim; an approval over the limit waits for sign-off."""
    body = {
        "decision": decision,
        "payout": payout,
        "section": section,
        "reason": reason,
    }
    return _call("POST", f"/api/claims/{claim_id}/decision", body)


def pay_claim(claim_id: str, amount: float) -> dict[str, Any]:
    """Pay an approved claim its payout, unless it needs a handler's sign-off."""
    return _call("POST", f"/api/claims/{claim_id}/payment", {"amount": amount})


def fail_claim(claim_id: str, error: str) -> dict[str, Any]:
    """Record a failed attempt: the claim goes back in the queue, or to a handler."""
    return _call("POST", f"/api/claims/{claim_id}/failure", {"error": error})


def start_run(run_id: str, cap: int) -> dict[str, Any]:
    """Start a run, first failing any claim a stopped run left in progress."""
    return _call("POST", "/api/runs", {"run_id": run_id, "cap": cap})


def write_todos(run_id: str, todos: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Replace a run's to-do list."""
    return _call("PUT", f"/api/runs/{run_id}/todos", {"todos": todos})


def finish_run(run_id: str, summary: str) -> dict[str, Any]:
    """Finish a run with a short summary for the handlers."""
    return _call("POST", f"/api/runs/{run_id}/finish", {"summary": summary})
