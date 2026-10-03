"""The provider-neutral shapes every backend speaks.

Messages use the chat-completions layout (`system`, `user`, `assistant` with `tool_calls`, `tool`), because
that is what the prompts are written in; a backend translates them to its own API. An assistant message a
backend returns may carry private keys (prefixed `_`) that only that backend reads back, such as the raw
content blocks a model needs to see again on the next turn.
"""

import re
from dataclasses import dataclass, field
from typing import Any, Protocol

# Billing or daily caps: waiting a minute will not help, so these are not retried.
QUOTA_RE = re.compile(r"insufficient_quota|credit balance|billing|usage limit|spend limit|quota (exceeded|exhausted)"
                      r"|per 86400s|per day|daily (limit|quota)", re.I)


@dataclass
class ToolSpec:
    name: str
    description: str
    schema: dict[str, Any]


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: str  # JSON text, as the model produced it


@dataclass
class Completion:
    text: str
    tool_calls: list[ToolCall]
    assistant_message: dict[str, Any]  # ready to append to the conversation
    prompt_tokens: int = 0
    completion_tokens: int = 0


class BackendError(Exception):
    """A call failed in a way the client reports as an LLM error."""


@dataclass
class RateLimited(BackendError):
    message: str
    retry_after_s: float | None = None
    quota: bool = False  # a billing or daily cap rather than a per-minute limit

    def __str__(self) -> str:
        return self.message


class ToolChoiceRejected(BackendError):
    """The model does not accept a forced tool call; the client falls back to `auto`."""


@dataclass
class ModelCheck:
    missing: list[str] = field(default_factory=list)
    similar: dict[str, list[str]] = field(default_factory=dict)


class Backend(Protocol):
    name: str

    def create(self, model: str, messages: list[dict[str, Any]], tools: list[ToolSpec], force: str | None,
               max_tokens: int) -> Completion:
        """One model call. `force` names the tool the model must call, None leaves the choice to the model."""
        ...

    def forces_tools(self, model: str) -> bool:
        """Whether a forced tool call is worth trying for this model at all."""
        ...

    def check_models(self, models: list[str]) -> ModelCheck:
        """Which of `models` the provider does not serve; empty when it cannot tell."""
        ...


def is_quota(message: str) -> bool:
    return bool(QUOTA_RE.search(message))
