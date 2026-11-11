"""The queue agent, which works the queue by handing each claim to a claim agent."""

import uuid
from typing import Any

from langchain.agents import create_agent
from langchain.agents.middleware import (
    AgentMiddleware,
    ModelCallLimitMiddleware,
    ModelRetryMiddleware,
    ToolErrorMiddleware,
)
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import ToolMessage
from langgraph.checkpoint.memory import InMemorySaver

from agent import api, main
from agent.tools import QUEUE_TOOLS, RunContext

REMINDERS = 2


def waiting_claims() -> list[str]:
    """List the ids of the claims waiting in the queue."""
    return [
        claim["claim_id"] for claim in api.list_claims() if claim["status"] == "waiting"
    ]


def missed_claims(run: RunContext) -> list[str]:
    """Waiting claims within the cap: those back in the queue, then any still room."""
    waiting = waiting_claims()
    again = [claim_id for claim_id in waiting if claim_id in run.started]
    new = [claim_id for claim_id in waiting if claim_id not in run.started]
    return again + new[: run.cap - len(run.started)]


def converse(agent: Any, message: str, run: RunContext) -> str:
    """Send the queue agent a message, print each claim's line, and return its reply."""
    states = agent.stream(
        {"messages": [{"role": "user", "content": message}]},
        config={"configurable": {"thread_id": run.run_id}},
        context=run,
        stream_mode="values",
    )
    messages = next(states)["messages"]
    for state in states:
        for new in state["messages"][len(messages) :]:
            if isinstance(new, ToolMessage) and new.name == "work_claim":
                print(new.text, flush=True)
        messages = state["messages"]
    return messages[-1].text


def work_queue(
    cap: int | None = None,
    llm: BaseChatModel | None = None,
    claim_llm: BaseChatModel | None = None,
) -> None:
    """Work the waiting claims up to the cap, printing each line and the summary."""
    waiting = waiting_claims()
    if not waiting:
        print("No claims are waiting.")
        return
    cap = len(waiting) if cap is None else cap
    run = RunContext(
        str(uuid.uuid4()), cap, lambda claim_id: main.work_claim(claim_id, claim_llm)
    )
    api.start_run(run.run_id, cap)
    middleware: list[AgentMiddleware[Any, Any, Any]] = [
        ModelRetryMiddleware(max_retries=3, on_failure="error"),
        ToolErrorMiddleware(main.refusal),
        ModelCallLimitMiddleware(thread_limit=4 * cap + 10, exit_behavior="end"),
    ]
    agent = create_agent(
        llm or main.model(),
        tools=QUEUE_TOOLS,
        system_prompt=api.get_instructions()["queue"],
        middleware=middleware,
        context_schema=RunContext,
        checkpointer=InMemorySaver(),
    )
    try:
        summary = converse(
            agent, f"Work the waiting claims in the queue, up to {cap}.", run
        )
        for _ in range(REMINDERS):
            missed = missed_claims(run)
            if not missed:
                break
            summary = converse(
                agent,
                f"These claims are still waiting within your cap: {', '.join(missed)}."
                " Work them and update your to-do list, then finish with your summary.",
                run,
            )
    except Exception as error:  # the run stops, and says why on the queue page
        summary = f"The run stopped: {error}"
    summary = summary or "The agent finished without a summary."
    api.finish_run(run.run_id, summary)
    print(f"\n{summary}")
