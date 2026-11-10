"""The queue agent, which works the queue by handing each claim to a claim agent."""

import uuid
from typing import Any, Literal, TypedDict

from langchain.agents import create_agent
from langchain.agents.middleware import (
    AgentMiddleware,
    ModelCallLimitMiddleware,
    ModelRetryMiddleware,
)
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import ToolMessage
from langchain_core.tools import BaseTool, tool
from langgraph.checkpoint.memory import InMemorySaver

from agent import main
from agent.tools import list_claims, reply, request

REMINDERS = 2


class Todo(TypedDict):
    content: str
    status: Literal["to_do", "in_progress", "done", "left_for_handler"]


def queue_tools(
    run_id: str, cap: int, started: list[str], claim_llm: BaseChatModel | None
) -> list[BaseTool]:
    """Give the queue agent its tools for this run."""

    @tool
    def write_todos(todos: list[Todo]) -> str:
        """Replace this run's to-do list, which the claims team watches."""
        return reply(request("PUT", f"/api/runs/{run_id}/todos", {"todos": todos}))

    @tool
    def work_claim(claim_id: str) -> str:
        """Hand a waiting claim to a fresh claim agent, which reports back in a line."""
        response = request("GET", f"/api/claims/{claim_id}")
        if response.is_error:
            return reply(response)
        status = response.json()["status"]
        if status != "waiting":
            return f"Refused: {claim_id} is not waiting, it is {status}."
        if claim_id not in started:
            if len(started) >= cap:
                return f"Refused: this run is capped at {cap} claims."
            started.append(claim_id)
        return main.work_claim(claim_id, claim_llm)

    return [list_claims, write_todos, work_claim]


def waiting_claims() -> list[str]:
    """List the ids of the claims waiting in the queue."""
    return [
        claim["claim_id"]
        for claim in main.call_backend("GET", "/api/claims")
        if claim["status"] == "waiting"
    ]


def missed_claims(started: list[str], cap: int) -> list[str]:
    """Waiting claims within the cap: those back in the queue, then any still room."""
    waiting = waiting_claims()
    again = [claim_id for claim_id in waiting if claim_id in started]
    new = [claim_id for claim_id in waiting if claim_id not in started]
    return again + new[: cap - len(started)]


def converse(agent: Any, message: str, thread_id: str) -> str:
    """Send the queue agent a message, print each claim's line, and return its reply."""
    states = agent.stream(
        {"messages": [{"role": "user", "content": message}]},
        config={"configurable": {"thread_id": thread_id}},
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
    cap = cap or len(waiting)
    run_id = str(uuid.uuid4())
    main.call_backend("POST", "/api/runs", {"run_id": run_id, "cap": cap})
    started: list[str] = []
    middleware: list[AgentMiddleware[Any, Any, Any]] = [
        ModelRetryMiddleware(max_retries=3, on_failure="error"),
        ModelCallLimitMiddleware(thread_limit=4 * cap + 10, exit_behavior="end"),
    ]
    agent = create_agent(
        llm or main.model(),
        tools=queue_tools(run_id, cap, started, claim_llm),
        system_prompt=main.call_backend("GET", "/api/instructions")["queue"],
        middleware=middleware,
        checkpointer=InMemorySaver(),
    )
    try:
        summary = converse(
            agent, f"Work the waiting claims in the queue, up to {cap}.", run_id
        )
        for _ in range(REMINDERS):
            missed = missed_claims(started, cap)
            if not missed:
                break
            summary = converse(
                agent,
                f"These claims are still waiting within your cap: {', '.join(missed)}."
                " Work them and update your to-do list, then finish with your summary.",
                run_id,
            )
    except Exception as error:  # the run stops, and says why on the queue page
        summary = f"The run stopped: {error}"
    summary = summary or "The agent finished without a summary."
    main.call_backend("POST", f"/api/runs/{run_id}/finish", {"summary": summary})
    print(f"\n{summary}")
