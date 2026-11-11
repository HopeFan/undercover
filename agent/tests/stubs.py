"""Stand-ins for the model in tests, which never call a real one."""

from collections.abc import Iterator

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult

UNAVAILABLE = RuntimeError("The model is unavailable")


class StubModel(BaseChatModel):
    """A chat model that gives scripted replies, or raises a scripted error,
    and keeps the prompts it was sent."""

    messages: Iterator[AIMessage | Exception]
    prompts: list[list[BaseMessage]] = []

    @property
    def _llm_type(self):
        return "stub"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.prompts.append(messages)
        reply = next(self.messages)
        if isinstance(reply, Exception):
            raise reply
        return ChatResult(generations=[ChatGeneration(message=reply)])


def call(name, text="", **args):
    return AIMessage(
        content=text, tool_calls=[{"name": name, "args": args, "id": f"call-{name}"}]
    )


def script(decision, payout, *extra):
    return StubModel(
        messages=iter(
            [
                call("get_claim"),
                call("get_policy"),
                call("get_claim_history"),
                call(
                    "record_decision",
                    decision=decision,
                    payout=payout,
                    section="Section 3, Trip Delay",
                    reason="The delay was covered.",
                ),
                *extra,
                AIMessage(content=f"Decision: {decision}."),
            ]
        )
    )
