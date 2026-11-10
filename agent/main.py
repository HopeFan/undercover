"""The UnderCover Agent."""

import json
import os
import uuid
from collections import Counter
from typing import Any

from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AnyMessage, ToolMessage
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import SecretStr

from agent.tools import REFUSED, TOOLS, request

load_dotenv(override=True)

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_MODEL = "deepseek/deepseek-v4.1-flash"
DOCUMENT_NAMES = {"policy_wording": "Policy wording", "claims_manual": "Claims manual"}


def model() -> ChatOpenAI:
    """Return the model named in MODEL_NAME, or DeepSeek V4.1 Flash by default."""
    name = os.getenv("MODEL_NAME")
    return ChatOpenAI(
        model=name or DEFAULT_MODEL,
        base_url=OPENROUTER_BASE_URL,
        api_key=SecretStr(os.environ["OPENROUTER_API_KEY"]),
        reasoning_effort=None if name else "low",
    )


class BackendError(Exception):
    """The backend refused a request the agent's run depends on."""


def call_backend(method: str, path: str, body: dict[str, Any] | None = None) -> Any:
    """Call the backend and return its JSON, raising if it refuses."""
    response = request(method, path, body)
    if response.is_error:
        raise BackendError(f"{response.status_code}: {response.json()['detail']}")
    return response.json()


def read_step(section: dict[str, Any]) -> str:
    """Name a section the agent read, followed by its text."""
    name = DOCUMENT_NAMES[section["document"]]
    return (
        f"{name}, section {section['section']}: {section['title']}\n\n{section['text']}"
    )


def steps(message: AnyMessage) -> list[tuple[str, str]]:
    """Turn one message from the agent's run into steps for the dashboard."""
    if isinstance(message, ToolMessage):
        if message.name == "read_section" and not message.text.startswith(REFUSED):
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
    call_backend("POST", f"/api/claims/{claim_id}/start", {"thread_id": thread_id})
    instructions = call_backend("GET", "/api/instructions")["text"]
    agent = create_agent(
        llm or model(),
        tools=TOOLS,
        system_prompt=instructions,
        checkpointer=InMemorySaver(),
    )
    states = agent.stream(
        {"messages": [{"role": "user", "content": f"Claim {claim_id}"}]},
        config={"configurable": {"thread_id": thread_id}},
        stream_mode="values",
    )
    messages = next(states)["messages"]
    for state in states:
        for message in state["messages"][len(messages) :]:
            for kind, content in steps(message):
                call_backend(
                    "POST",
                    f"/api/claims/{claim_id}/steps",
                    {"kind": kind, "content": content},
                )
        messages = state["messages"]
    return messages[-1].text


def work_queue() -> None:
    """Work every waiting claim in queue order, printing each decision and a count."""
    outcomes: Counter[str] = Counter()
    for claim in call_backend("GET", "/api/claims"):
        if claim["status"] != "waiting":
            continue
        claim_id = claim["claim_id"]
        try:
            run(claim_id, str(uuid.uuid4()))
        except Exception as error:  # one failed claim shouldn't stop the queue
            print(f"{claim_id}  failed: {error}", flush=True)
            outcomes["failed"] += 1
            continue
        decision = call_backend("GET", f"/api/claims/{claim_id}")["decision"]
        if decision is None:
            print(f"{claim_id}  undecided", flush=True)
            outcomes["undecided"] += 1
        else:
            outcome = decision["decision"]
            print(f"{claim_id}  {outcome}  ${decision['payout']:,.2f}", flush=True)
            outcomes[outcome] += 1
    counts = ", ".join(f"{outcomes[name]} {name}" for name in sorted(outcomes))
    print(f"Worked {outcomes.total()} claims: {counts or 'none waiting'}")
