"""The UnderCover Agent's harness: the model, the middleware, and the two agents.
A queue agent works a run and hands each claim to a fresh claim agent."""

import json
import os
import uuid
from collections.abc import Callable
from typing import Any

from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain.agents.middleware import (
    AgentMiddleware,
    ModelCallLimitMiddleware,
    ModelRetryMiddleware,
    ToolCallRequest,
    ToolErrorMiddleware,
    ToolRetryMiddleware,
)
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AnyMessage, ToolMessage
from langchain_core.tools import BaseTool
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph.state import CompiledStateGraph
from langgraph.typing import ContextT
from pydantic import SecretStr

from agent import api
from agent.tools import (
    CLAIM_TOOLS,
    QUEUE_TOOLS,
    ClaimContext,
    Refused,
    RunContext,
    list_claims,
    write_todos,
)

load_dotenv(override=True)

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_MODEL = "deepseek/deepseek-v4.1-flash"
MODEL_TIMEOUT = 60
MODEL_RETRIES = 3
TOOL_RETRIES = 2
CLAIM_MODEL_CALLS = 30
QUEUE_MODEL_CALLS_PER_CLAIM = 4
QUEUE_SPARE_MODEL_CALLS = 10
REMINDERS = 2
DOCUMENT_NAMES = {"policy_wording": "Policy wording", "claims_manual": "Claims manual"}


def model() -> ChatOpenAI:
    """Return the model named in MODEL_NAME, or DeepSeek V4.1 Flash by default."""
    name = os.getenv("MODEL_NAME")
    return ChatOpenAI(
        model=name or DEFAULT_MODEL,
        base_url=OPENROUTER_BASE_URL,
        api_key=SecretStr(os.environ["OPENROUTER_API_KEY"]),
        reasoning_effort=None if name else "low",
        timeout=MODEL_TIMEOUT,
    )


def refusal(error: Exception, request: ToolCallRequest) -> str | None:
    """Give the model the reason a request was refused; other errors stop the run."""
    if isinstance(error, api.ApiError):
        return f"Refused with status {error}"
    if isinstance(error, Refused):
        return f"Refused: {error}"
    return None


def retry(tools: list[BaseTool]) -> ToolRetryMiddleware:
    """Retry these tools when the backend can't be reached; a refusal is final."""
    return ToolRetryMiddleware(
        max_retries=TOOL_RETRIES,
        tools=[*tools],
        retry_on=(api.ApiUnavailable,),
        on_failure="error",
    )


def build_agent(
    llm: BaseChatModel,
    tools: list[BaseTool],
    instructions: str,
    context_schema: type[ContextT],
    own_middleware: list[AgentMiddleware[Any, Any, Any]],
) -> CompiledStateGraph[Any, ContextT, Any, Any]:
    """Build an agent with the middleware both agents share, then its own."""
    middleware: list[AgentMiddleware[Any, Any, Any]] = [
        ModelRetryMiddleware(max_retries=MODEL_RETRIES, on_failure="error"),
        ToolErrorMiddleware(refusal),
        *own_middleware,
    ]
    return create_agent(
        llm,
        tools=tools,
        system_prompt=instructions,
        middleware=middleware,
        context_schema=context_schema,
        checkpointer=InMemorySaver(),
    )


def stream(
    agent: CompiledStateGraph[Any, ContextT, Any, Any],
    message: str,
    thread_id: str,
    context: ContextT,
    on_message: Callable[[AnyMessage], None],
) -> str:
    """Send an agent a message, pass on each new message, and return its reply."""
    states = agent.stream(
        {"messages": [{"role": "user", "content": message}]},
        config={"configurable": {"thread_id": thread_id}},
        context=context,
        stream_mode="values",
    )
    messages = next(states)["messages"]
    for state in states:
        for new in state["messages"][len(messages) :]:
            on_message(new)
        messages = state["messages"]
    return messages[-1].text


def read_step(section: dict[str, Any]) -> str:
    """Name a section the agent read, followed by its text."""
    name = DOCUMENT_NAMES[section["document"]]
    return (
        f"{name}, section {section['section']}: {section['title']}\n\n{section['text']}"
    )


def steps(message: AnyMessage) -> list[tuple[str, str]]:
    """Turn one message from the agent's run into steps for the dashboard."""
    if isinstance(message, ToolMessage):
        if message.name == "read_section" and message.status != "error":
            return [("read", read_step(json.loads(message.text)))]
        return [("tool_result", f"{message.name}: {message.text}")]
    found = []
    if message.text:
        found.append(("message", message.text))
    if isinstance(message, AIMessage):
        for call in message.tool_calls:
            args = ", ".join(f"{k}={json.dumps(v)}" for k, v in call["args"].items())
            found.append(("tool_call", f"{call['name']}({args})"))
    return found


def record_steps(claim_id: str, message: AnyMessage) -> None:
    """Record one message from the claim agent as steps on its claim."""
    for kind, content in steps(message):
        api.record_step(claim_id, kind, content)


def run_claim_agent(
    claim_id: str, thread_id: str, llm: BaseChatModel | None = None
) -> str:
    """Work one claim, recording each step with the backend, and return the reply."""
    claim = api.start_claim(claim_id, thread_id)
    context = ClaimContext(claim_id, claim["policy_id"], claim["customer_id"])
    agent = build_agent(
        llm or model(),
        CLAIM_TOOLS,
        api.get_instructions()["claim"],
        ClaimContext,
        [
            retry(CLAIM_TOOLS),
            ModelCallLimitMiddleware(
                run_limit=CLAIM_MODEL_CALLS, exit_behavior="error"
            ),
        ],
    )
    return stream(
        agent,
        f"Claim {claim_id}",
        thread_id,
        context,
        lambda message: record_steps(claim_id, message),
    )


def report(claim: dict[str, Any]) -> str:
    """Give a decided claim's outcome in one line."""
    decision = claim["decision"]
    line = f"{claim['claim_id']}  {decision['decision']}  ${decision['payout']:,.2f}"
    if claim["status"] == "waiting_for_sign_off":
        line += "  waiting for sign-off"
    return line


def settle(claim: dict[str, Any]) -> None:
    """Pay an approval within the limit that the agent left unpaid."""
    decision = claim["decision"]
    if (
        claim["status"] == "decided"
        and decision["decision"] == "approve"
        and claim["payment"] is None
    ):
        api.pay_claim(claim["claim_id"], decision["payout"])


def work_claim(claim_id: str, llm: BaseChatModel | None = None) -> str:
    """Work one claim with a fresh claim agent and report the outcome in one line."""
    thread_id = str(uuid.uuid4())
    error = None
    try:
        run_claim_agent(claim_id, thread_id, llm)
    except Exception as failure:  # one bad claim must never stop a run
        error = str(failure) or type(failure).__name__
    claim = api.get_claim(claim_id)
    if claim["thread_id"] != thread_id:  # another attempt holds it, so leave it be
        return f"{claim_id}  not started: {error}"
    if claim["status"] == "in_progress":
        error = error or "The agent finished without recording a decision"
        status = api.fail_claim(claim_id, error)["status"]
        where = "Back in the queue." if status == "waiting" else "Left for a handler."
        return f"{claim_id}  failed: {error}. {where}"
    if error:
        api.record_step(claim_id, "error", error)
    settle(claim)
    return report(claim)


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


def print_claim_line(message: AnyMessage) -> None:
    """Print each line a claim agent reports back to the queue agent."""
    if isinstance(message, ToolMessage) and message.name == "work_claim":
        print(message.text, flush=True)


def converse(
    agent: CompiledStateGraph[Any, RunContext, Any, Any], run: RunContext
) -> str:
    """Have the queue agent work the run, reminding it of missed claims, and return
    its summary."""
    try:
        message = f"Work the waiting claims in the queue, up to {run.cap}."
        summary = stream(agent, message, run.run_id, run, print_claim_line)
        for _ in range(REMINDERS):
            missed = missed_claims(run)
            if not missed:
                break
            message = (
                f"These claims are still waiting within your cap: {', '.join(missed)}."
                " Work them and update your to-do list, then finish with your summary."
            )
            summary = stream(agent, message, run.run_id, run, print_claim_line)
    except Exception as error:  # the run stops, and says why on the queue page
        summary = f"The run stopped: {error}"
    return summary or "The agent finished without a summary."


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
        str(uuid.uuid4()), cap, lambda claim_id: work_claim(claim_id, claim_llm)
    )
    api.start_run(run.run_id, cap)
    calls = QUEUE_MODEL_CALLS_PER_CLAIM * cap + QUEUE_SPARE_MODEL_CALLS
    agent = build_agent(
        llm or model(),
        QUEUE_TOOLS,
        api.get_instructions()["queue"],
        RunContext,
        [
            retry([list_claims, write_todos]),
            ModelCallLimitMiddleware(thread_limit=calls, exit_behavior="end"),
        ],
    )
    summary = converse(agent, run)
    api.finish_run(run.run_id, summary)
    print(f"\n{summary}")
