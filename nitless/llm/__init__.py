"""LLM access for every pipeline step, independent of the provider behind it.

Structured answers come from a single tool call validated against a pydantic schema: forced where the model
allows it, otherwise steered by the prompt and retried once. `preflight` checks every configured model before
any work starts, so a typo in a model name fails in seconds, not mid-review.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from typing import TYPE_CHECKING, Any, Protocol, TypeVar

from pydantic import BaseModel, ValidationError

from nitless.errors import ConfigError, LLMError, QuotaExhaustedError
from nitless.llm.base import Backend, BackendError, Completion, RateLimited, ToolChoiceRejected, ToolSpec
from nitless.llm.providers import make_backend
from nitless.models import ModelUsage

if TYPE_CHECKING:
    from nitless.config import Settings

log = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

RATE_LIMIT_PAUSE_S = 30
AGENT_TIME_BUDGET_S = 300


class AgentTools(Protocol):
    """What `run_agent` needs from a toolbox: tool specs, a budget flag and a way to run a call."""

    specs: list[dict[str, Any]]

    @property
    def exhausted(self) -> bool: ...

    def call(self, name: str, args: dict[str, Any]) -> str: ...


class LLMClient:
    def __init__(self, settings: Settings, backend: Backend | None = None):
        self.settings = settings
        self.backend = backend or make_backend(
            settings.llm_provider, settings.llm_key, settings.llm_base_url, settings.llm_timeout_s,
            settings.llm_max_retries)
        self._forced: dict[str, bool] = {}
        self.usage: dict[str, ModelUsage] = {}  # by model
        self.usage_by_tool: dict[str, ModelUsage] = {}  # by pipeline step (tool name), for the context trace
        self._usage_lock = threading.Lock()  # pipeline steps call the client from several threads

    def preflight(self, model_ids: list[str]) -> None:
        try:
            check = self.backend.check_models(list(dict.fromkeys(model_ids)))
        except BackendError as e:
            raise LLMError(str(e)) from None
        if check.missing:
            model = check.missing[0]
            similar = ", ".join(check.similar.get(model, [])) or "-"
            raise ConfigError(f"model {model!r} is not available on {self.backend.name}. Similar: {similar}")

    def call_tool(self, model: str, messages: list[dict[str, Any]], tool_name: str, tool_description: str,
                  schema: type[T], max_tokens: int | None = None) -> T:
        """Have the model answer by calling a single tool, and validate its arguments against `schema`."""
        tool = _tool_spec(tool_name, tool_description, schema)
        last_error = ""
        for attempt in range(2):
            convo = messages if attempt == 0 else [*messages, {
                "role": "user", "content": f"Your previous answer was invalid: {last_error}. Call {tool_name} again."}]
            response = self._create(model, convo, [tool], tool_name, max_tokens, tool_name)
            call = next((c for c in response.tool_calls if c.name == tool_name), None)
            if call is None:
                last_error = f"no {tool_name} call was made"
                continue
            try:
                return schema.model_validate(decode_arguments(call.arguments))
            except (json.JSONDecodeError, ValidationError) as e:
                last_error = str(e)[:500]
                log.warning("model %s returned invalid %s arguments: %s", model, tool_name, last_error)
        raise LLMError(f"model {model} did not return a valid {tool_name} call: {last_error}")

    def run_agent(self, model: str, messages: list[dict[str, Any]], tools: AgentTools, tool_name: str,
                  tool_description: str, schema: type[T], max_rounds: int, max_tokens: int | None = None,
                  time_budget_s: float = AGENT_TIME_BUDGET_S) -> T:
        """Let the model explore with `tools`, then answer by calling `tool_name` (validated against `schema`).

        Up to `max_rounds` rounds of tool calls with the choice left to the model; once the rounds, the toolbox
        budget or the time budget run out, only the answer tool is offered (forced where the model allows it).
        """
        answer = _tool_spec(tool_name, tool_description, schema)
        explore_specs = [ToolSpec(s["function"]["name"], s["function"].get("description", ""),
                                  s["function"]["parameters"]) for s in tools.specs]
        convo = list(messages)
        deadline = time.monotonic() + time_budget_s
        wrapped_up, last_error = False, ""
        for round_no in range(max_rounds + 2):  # the rounds, the answer, one retry of an invalid answer
            explore = round_no < max_rounds and not tools.exhausted and time.monotonic() < deadline
            if not explore and not wrapped_up:
                convo.append({"role": "user", "content": f"No more tool calls are available. Call {tool_name} now."})
                wrapped_up = True
            response = self._create(model, convo, [*explore_specs, answer] if explore else [answer],
                                    None if explore else tool_name, max_tokens, tool_name)
            calls = response.tool_calls
            submit = next((c for c in calls if c.name == tool_name), None)
            if submit is not None:
                try:
                    return schema.model_validate(decode_arguments(submit.arguments))
                except (json.JSONDecodeError, ValidationError) as e:
                    last_error = str(e)[:500]
                    log.warning("model %s returned invalid %s arguments: %s", model, tool_name, last_error)
            if not calls:
                last_error = f"no {tool_name} call was made"
                convo += [{"role": "assistant", "content": response.text or "(no answer)"},
                          {"role": "user", "content": f"Call {tool_name} with your answer."}]
                continue
            convo.append(response.assistant_message)
            for c in calls:
                result = f"Invalid arguments: {last_error}. Call {tool_name} again." if c is submit \
                    else tools.call(c.name, _tool_args(c.arguments))
                convo.append({"role": "tool", "tool_call_id": c.id, "content": result})
        raise LLMError(f"model {model} did not return a valid {tool_name} call: {last_error}")

    def _create(self, model: str, messages: list[dict[str, Any]], tools: list[ToolSpec], force: str | None,
                max_tokens: int | None, step: str) -> Completion:
        if force and not self._forced.setdefault(model, self.backend.forces_tools(model)):
            force = None  # the prompts ask for the tool call; callers retry when it is missing
        limit = max_tokens or self.settings.llm_max_output_tokens
        try:
            response = self._create_waiting_on_rate_limit(model, messages, tools, force, limit)
        except ToolChoiceRejected:
            log.info("%s rejects a forced tool call; leaving the choice to the model from now on", model)
            self._forced[model] = False
            return self._create(model, messages, tools, None, max_tokens, step)
        except RateLimited as e:
            if e.quota:
                raise QuotaExhaustedError(
                    f"{self.backend.name} quota or credit exhausted for {model}: {e}. Top up, wait for the reset, or "
                    "set MODEL_STRONG/MODEL_FAST to another model") from None
            raise LLMError(f"{self.backend.name} still refused {model} after waiting up to "
                           f"{self.settings.llm_rate_limit_wait_s:.0f}s (LLM_RATE_LIMIT_WAIT_S): {e}") from None
        except BackendError as e:
            raise LLMError(str(e)) from None
        self._record(model, response, self.usage)
        self._record(step, response, self.usage_by_tool)
        return response

    def _create_waiting_on_rate_limit(self, model: str, messages: list[dict[str, Any]], tools: list[ToolSpec],
                                      force: str | None, max_tokens: int) -> Completion:
        """Per-minute limits are waited out (up to LLM_RATE_LIMIT_WAIT_S); a spent quota is not."""
        deadline = time.monotonic() + self.settings.llm_rate_limit_wait_s
        while True:
            try:
                return self.backend.create(model, messages, tools, force, max_tokens)
            except RateLimited as e:
                pause = max(e.retry_after_s or RATE_LIMIT_PAUSE_S, 1)
                if e.quota or time.monotonic() + pause > deadline:
                    raise
                log.warning("%s rate-limited; waiting %.0fs", model, pause)
                time.sleep(pause)

    def _record(self, key: str, response: Completion, table: dict[str, ModelUsage]) -> None:
        with self._usage_lock:
            entry = table.setdefault(key, ModelUsage())
            entry.calls += 1
            entry.prompt_tokens += response.prompt_tokens
            entry.completion_tokens += response.completion_tokens


def _tool_spec(name: str, description: str, schema: type[BaseModel]) -> ToolSpec:
    return ToolSpec(name, description, schema.model_json_schema())


def _tool_args(raw: str) -> dict[str, Any]:
    try:
        value = decode_arguments(raw or "{}")
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def decode_arguments(raw: str) -> Any:
    """Parse tool arguments, unwrapping values some models JSON-encode twice.

    e.g. {"matches": "{\\"matches\\": [...]}"} or a whole-object string.
    """
    value = json.loads(raw)
    if isinstance(value, str):
        value = json.loads(value)
    if isinstance(value, dict):
        for key, inner in value.items():
            if isinstance(inner, str) and inner.lstrip()[:1] in ("{", "["):
                try:
                    decoded = json.loads(inner)
                except json.JSONDecodeError:
                    continue
                value[key] = decoded.get(key, decoded) if isinstance(decoded, dict) else decoded
    return value
