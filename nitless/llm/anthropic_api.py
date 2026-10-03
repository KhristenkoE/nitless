"""Claude through the official Anthropic SDK."""

import json
import re
from typing import Any

import anthropic

from nitless.llm.base import (
    BackendError,
    Completion,
    ModelCheck,
    RateLimited,
    ToolCall,
    ToolChoiceRejected,
    ToolSpec,
    is_quota,
)

# Models that answer a forced tool_choice with a 400; prompts steer them to the tool instead.
NO_FORCED_TOOLS = re.compile(r"claude-(opus-5-5|sonnet-5-5|fable-5-1|mythos-5-1)")


class AnthropicBackend:
    name = "anthropic"

    def __init__(self, api_key: str, base_url: str | None, timeout_s: float, max_retries: int):
        self._sdk = anthropic.Anthropic(api_key=api_key, base_url=base_url, timeout=timeout_s,
                                        max_retries=max_retries)

    def forces_tools(self, model: str) -> bool:
        return not NO_FORCED_TOOLS.search(model)

    def create(self, model: str, messages: list[dict[str, Any]], tools: list[ToolSpec], force: str | None,
               max_tokens: int) -> Completion:
        system, turns = to_anthropic(messages)
        params: dict[str, Any] = {
            "model": model, "max_tokens": max_tokens, "messages": turns,
            "tools": [{"name": t.name, "description": t.description, "input_schema": t.schema} for t in tools],
        }
        if system:
            params["system"] = system
        if force:
            params["tool_choice"] = {"type": "tool", "name": force}
        try:
            with self._sdk.messages.stream(**params) as stream:  # streaming: long reviews never hit read timeouts
                message = stream.get_final_message()
        except anthropic.RateLimitError as e:
            raise RateLimited(f"{model}: {e.message}", _retry_after(e), quota=is_quota(str(e.message))) from None
        except anthropic.BadRequestError as e:
            if force and "tool_choice" in str(e.message):
                raise ToolChoiceRejected(str(e.message)) from None
            if is_quota(str(e.message)):
                raise RateLimited(f"{model}: {e.message}", quota=True) from None
            raise BackendError(f"Anthropic call to {model} failed (400): {str(e.message)[:300]}") from None
        except anthropic.AuthenticationError:
            raise BackendError("Anthropic rejected the API key (401)") from None
        except anthropic.APIStatusError as e:
            raise BackendError(f"Anthropic call to {model} failed ({e.status_code}): {str(e.message)[:300]}") from None
        except anthropic.APIError as e:
            raise BackendError(f"Anthropic call to {model} failed: {e}") from None
        return from_anthropic(message)

    def check_models(self, models: list[str]) -> ModelCheck:
        check = ModelCheck()
        for model in models:
            try:
                self._sdk.models.retrieve(model)
            except anthropic.NotFoundError:
                check.missing.append(model)
            except anthropic.AuthenticationError:
                raise BackendError("Anthropic rejected the API key (401)") from None
            except anthropic.APIConnectionError as e:
                raise BackendError(f"cannot reach the Anthropic API: {e}") from None
            except anthropic.APIError:
                return ModelCheck()  # the listing is unavailable; the first call will tell
        if check.missing:
            try:
                known = [m.id for m in self._sdk.models.list()]
            except anthropic.APIError:
                known = []
            for model in check.missing:
                family = model.rsplit("-", 2)[0]
                check.similar[model] = sorted(k for k in known if k.startswith(family))[:8]
        return check


def to_anthropic(messages: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    """Chat-completions messages to an Anthropic system prompt and turns, merging consecutive same-role turns."""
    system: list[str] = []
    turns: list[dict[str, Any]] = []

    def add(role: str, blocks: list[dict[str, Any]]) -> None:
        if turns and turns[-1]["role"] == role:
            turns[-1]["content"].extend(blocks)
        else:
            turns.append({"role": role, "content": list(blocks)})

    for m in messages:
        role, content = m["role"], m.get("content")
        if role == "system":
            system.append(content or "")
        elif role == "tool":
            add("user", [{"type": "tool_result", "tool_use_id": m["tool_call_id"], "content": content or ""}])
        elif role == "assistant" and "_anthropic_content" in m:
            add("assistant", m["_anthropic_content"])
        elif role == "assistant":
            blocks: list[dict[str, Any]] = [{"type": "text", "text": content}] if content else []
            for c in m.get("tool_calls") or []:
                blocks.append({"type": "tool_use", "id": c["id"], "name": c["function"]["name"],
                               "input": json.loads(c["function"]["arguments"] or "{}")})
            add("assistant", blocks)
        else:
            add("user", [{"type": "text", "text": content or ""}])
    return "\n\n".join(system), turns


def from_anthropic(message: Any) -> Completion:
    text = "".join(b.text for b in message.content if b.type == "text")
    calls = [ToolCall(b.id, b.name, json.dumps(b.input)) for b in message.content if b.type == "tool_use"]
    # Thinking blocks go back to the model unchanged on the next turn of the same conversation.
    raw = [b.model_dump(exclude_none=True) for b in message.content]
    usage = message.usage
    prompt = (usage.input_tokens or 0) + (getattr(usage, "cache_read_input_tokens", 0) or 0) \
        + (getattr(usage, "cache_creation_input_tokens", 0) or 0)
    return Completion(
        text=text, tool_calls=calls,
        assistant_message={"role": "assistant", "content": text or None, "_anthropic_content": raw,
                           "tool_calls": [{"id": c.id, "type": "function",
                                           "function": {"name": c.name, "arguments": c.arguments}} for c in calls]},
        prompt_tokens=prompt, completion_tokens=usage.output_tokens or 0)


def _retry_after(e: anthropic.APIStatusError) -> float | None:
    try:
        return float(e.response.headers.get("retry-after"))
    except (TypeError, ValueError):
        return None
