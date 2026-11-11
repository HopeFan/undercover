"""The agent's tools, each named after the backend operation it calls."""

import json
from typing import Any, Literal

from langchain_core.tools import tool

from agent import api

Document = Literal["policy_wording", "claims_manual"]


def as_text(data: Any) -> str:
    """Give the model the backend's answer as JSON, so an empty list reads as []."""
    return json.dumps(data)


@tool
def list_claims() -> str:
    """List every claim in the queue, in id order."""
    return as_text(api.list_claims())


@tool
def get_claim(claim_id: str) -> str:
    """Get one claim in full: the story, the items claimed and the documents."""
    return as_text(api.get_claim(claim_id))


@tool
def get_policy(policy_id: str) -> str:
    """Get a policy: the plan, add-ons, purchase date, trip and travelers."""
    return as_text(api.get_policy(policy_id))


@tool
def get_claim_history(customer_id: str) -> str:
    """Get a customer's earlier claims, with the outcome and the amount paid."""
    return as_text(api.get_claim_history(customer_id))


@tool
def list_sections(document: Document) -> str:
    """List the numbered sections of the policy wording or the claims manual."""
    return as_text(api.list_sections(document))


@tool
def read_section(document: Document, section: int) -> str:
    """Read one numbered section of the policy wording or the claims manual."""
    return as_text(api.read_section(document, section))


@tool
def record_decision(
    claim_id: str,
    decision: Literal["approve", "decline", "refer"],
    payout: float,
    section: str,
    reason: str,
) -> str:
    """Record the decision on a claim; an approval over the limit waits for sign-off."""
    return as_text(api.record_decision(claim_id, decision, payout, section, reason))


@tool
def pay_claim(claim_id: str, amount: float) -> str:
    """Pay an approved claim its payout, unless it needs a handler's sign-off."""
    return as_text(api.pay_claim(claim_id, amount))


TOOLS = [
    get_claim,
    get_policy,
    get_claim_history,
    list_sections,
    read_section,
    record_decision,
    pay_claim,
]
