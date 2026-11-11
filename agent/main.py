"""The UnderCover Agent."""

import json
import os
import uuid
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
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import SecretStr

from agent import api
from agent.tools import CLAIM_TOOLS, ClaimContext, Refused

load_dotenv(override=True)

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_MODEL = "deepseek/deepseek-v4.1-flash"
DOCUMENT_NAMES = {"policy_wording": "Policy wording", "claims_manual": "Claims manual"}
MODEL_TIMEOUT = 60
CLAIM_MODEL_CALLS = 30


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


def run(claim_id: str, thread_id: str, llm: BaseChatModel | None = None) -> str:
    """Work one claim, recording each step with the backend, and return the reply."""
    claim = api.start_claim(claim_id, thread_id)
    context = ClaimContext(claim_id, claim["policy_id"], claim["customer_id"])
    instructions = api.get_instructions()["claim"]
    middleware: list[AgentMiddleware[Any, Any, Any]] = [
        ModelRetryMiddleware(max_retries=3, on_failure="error"),
        ToolErrorMiddleware(refusal),
        ToolRetryMiddleware(
            max_retries=2, retry_on=(api.ApiUnavailable,), on_failure="error"
        ),
        ModelCallLimitMiddleware(run_limit=CLAIM_MODEL_CALLS, exit_behavior="error"),
    ]
    agent = create_agent(
        llm or model(),
        tools=CLAIM_TOOLS,
        system_prompt=instructions,
        middleware=middleware,
        context_schema=ClaimContext,
        checkpointer=InMemorySaver(),
    )
    states = agent.stream(
        {"messages": [{"role": "user", "content": f"Claim {claim_id}"}]},
        config={"configurable": {"thread_id": thread_id}},
        context=context,
        stream_mode="values",
    )
    messages = next(states)["messages"]
    for state in states:
        for message in state["messages"][len(messages) :]:
            for kind, content in steps(message):
                api.record_step(claim_id, kind, content)
        messages = state["messages"]
    return messages[-1].text


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
        run(claim_id, thread_id, llm)
    except Exception as failure:  # one bad claim must never stop a run
        error = str(failure) or type(failure).__name__
    claim = api.get_claim(claim_id)
    if claim["thread_id"] != thread_id:
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
