"""The agents' tools. Each calls the backend operation it is named after, or hands
a claim to a claim agent. The tools that need the agent's claim or run get it from
LangChain's context, never from the model."""

import json
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal, TypedDict

from langchain.tools import ToolRuntime
from langchain_core.tools import tool

from agent import api

Document = Literal["policy_wording", "claims_manual"]
RESERVING = threading.Lock()


@dataclass(frozen=True)
class ClaimContext:
    """The claim a claim agent is working, with its policy and its customer."""

    claim_id: str
    policy_id: str
    customer_id: str


@dataclass
class RunContext:
    """A run of the queue agent: its id, its cap, how to hand a claim to a claim
    agent, and the claims it has started.

    `started` is the one field a tool changes, only through `reserve`. It lives
    here rather than in the graph's state because each tool call runs on its own:
    parallel `work_claim` calls would each read the same snapshot of state, while
    this list, behind the RESERVING lock, counts every claim as soon as it starts."""

    run_id: str
    cap: int
    claim_worker: Callable[[str], str]
    started: list[str] = field(default_factory=list)

    def reserve(self, claim_id: str) -> bool:
        """Count a claim against the cap, or say no if the run is full."""
        with RESERVING:
            if claim_id not in self.started:
                if len(self.started) >= self.cap:
                    return False
                self.started.append(claim_id)
            return True


class Todo(TypedDict):
    content: str
    status: Literal["to_do", "in_progress", "done", "left_for_handler"]


class Refused(Exception):
    """A tool turned down the model's request, with the reason to give it."""


def as_text(data: Any) -> str:
    """Give the model the backend's answer as JSON, so an empty list reads as []."""
    return json.dumps(data)


@tool
def get_claim(runtime: ToolRuntime[ClaimContext]) -> str:
    """Get this claim in full: the story, the items claimed and the documents."""
    return as_text(api.get_claim(runtime.context.claim_id))


@tool
def get_policy(runtime: ToolRuntime[ClaimContext]) -> str:
    """Get this claim's policy: the plan, add-ons, purchase date, trip and travelers."""
    return as_text(api.get_policy(runtime.context.policy_id))


@tool
def get_claim_history(runtime: ToolRuntime[ClaimContext]) -> str:
    """Get the customer's earlier claims, with the outcome and the amount paid."""
    return as_text(api.get_claim_history(runtime.context.customer_id))


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
    decision: Literal["approve", "decline", "refer"],
    payout: float,
    section: str,
    reason: str,
    runtime: ToolRuntime[ClaimContext],
) -> str:
    """Record this claim's decision; an approval over the limit waits for sign-off."""
    claim_id = runtime.context.claim_id
    return as_text(api.record_decision(claim_id, decision, payout, section, reason))


@tool
def pay_claim(amount: float, runtime: ToolRuntime[ClaimContext]) -> str:
    """Pay this claim its approved payout, unless it needs a handler's sign-off."""
    return as_text(api.pay_claim(runtime.context.claim_id, amount))


@tool
def list_claims() -> str:
    """List every claim in the queue, in id order."""
    return as_text(api.list_claims())


@tool
def write_todos(todos: list[Todo], runtime: ToolRuntime[RunContext]) -> str:
    """Replace this run's to-do list, which the claims team watches."""
    return as_text(api.write_todos(runtime.context.run_id, todos))


@tool
def work_claim(claim_id: str, runtime: ToolRuntime[RunContext]) -> str:
    """Hand a waiting claim to a fresh claim agent, which reports back in a line."""
    run = runtime.context
    status = api.get_claim(claim_id)["status"]
    if status != "waiting":
        raise Refused(f"{claim_id} is not waiting, it is {status}.")
    if not run.reserve(claim_id):
        raise Refused(f"this run is capped at {run.cap} claims.")
    return run.claim_worker(claim_id)


CLAIM_TOOLS = [
    get_claim,
    get_policy,
    get_claim_history,
    list_sections,
    read_section,
    record_decision,
    pay_claim,
]
QUEUE_TOOLS = [list_claims, write_todos, work_claim]
