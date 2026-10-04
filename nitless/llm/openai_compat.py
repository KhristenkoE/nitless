"""Any chat-completions endpoint: OpenAI, Gemini, GitHub Models, OpenRouter, Ollama, vLLM, LM Studio."""

from typing import Any

import openai

from nitless.llm.base import (
    BackendError,
    Completion,
    ModelCheck,
    RateLimited,
    ToolCall,
    ToolChoiceRejected,
    ToolSpec,
    is_quota,
    retry_delay_s,
)


class OpenAICompatBackend:
    def __init__(self, name: str, api_key: str, base_url: str | None, timeout_s: float, max_retries: int):
        self.name = name
        self._sdk = openai.OpenAI(api_key=api_key or "unused", base_url=base_url, timeout=timeout_s,
                                  max_retries=max_retries)
        # OpenAI's newer models want max_completion_tokens; most compatible servers only know max_tokens.
        self._max_tokens_param = "max_completion_tokens" if name == "openai" else "max_tokens"
        self._no_forced: set[str] = set()

    def forces_tools(self, model: str) -> bool:
        return model not in self._no_forced

    def create(self, model: str, messages: list[dict[str, Any]], tools: list[ToolSpec], force: str | None,
               max_tokens: int, retry_param: bool = True) -> Completion:
        params: dict[str, Any] = {
            "model": model, "messages": [_public(m) for m in messages], self._max_tokens_param: max_tokens,
            "tools": [{"type": "function", "function": {"name": t.name, "description": t.description,
                                                        "parameters": t.schema}} for t in tools],
            "tool_choice": {"type": "function", "function": {"name": force}} if force else "auto",
        }
        try:
            response = self._sdk.chat.completions.create(**params)
        except openai.RateLimitError as e:
            body = f"{e.message} {e.body}"
            retry = _retry_after(e) or retry_delay_s(body)
            raise RateLimited(f"{model}: {str(e.message)[:300]}", retry, quota=is_quota(body)) from None
        except openai.BadRequestError as e:
            text = str(e.message)
            if force and "tool_choice" in text:
                self._no_forced.add(model)
                raise ToolChoiceRejected(text) from None
            if retry_param and self._max_tokens_param in text and "support" in text.lower():
                self._max_tokens_param = ({"max_tokens", "max_completion_tokens"} - {self._max_tokens_param}).pop()
                return self.create(model, messages, tools, force, max_tokens, retry_param=False)
            raise BackendError(f"{self.name} call to {model} failed (400): {text[:300]}") from None
        except openai.AuthenticationError:
            raise BackendError(f"{self.name} rejected the API key (401)") from None
        except openai.APIStatusError as e:
            if is_quota(str(e.message)):
                raise RateLimited(f"{model}: {str(e.message)[:300]}", quota=True) from None
            raise BackendError(f"{self.name} call to {model} failed ({e.status_code}): {str(e.message)[:300]}") \
                from None
        except openai.APIError as e:
            raise BackendError(f"{self.name} call to {model} failed: {e}") from None
        message = response.choices[0].message
        calls = [ToolCall(c.id, c.function.name, c.function.arguments or "{}") for c in message.tool_calls or []]
        assistant: dict[str, Any] = {"role": "assistant", "content": message.content or None}
        if calls:
            assistant["tool_calls"] = [{"id": c.id, "type": "function",
                                        "function": {"name": c.name, "arguments": c.arguments}} for c in calls]
        usage = response.usage
        return Completion(text=message.content or "", tool_calls=calls, assistant_message=assistant,
                          prompt_tokens=(usage.prompt_tokens or 0) if usage else 0,
                          completion_tokens=(usage.completion_tokens or 0) if usage else 0)

    def check_models(self, models: list[str]) -> ModelCheck:
        try:
            known = {m.id.removeprefix("models/") for m in self._sdk.models.list()}
        except openai.AuthenticationError:
            raise BackendError(f"{self.name} rejected the API key (401)") from None
        except openai.APIConnectionError as e:
            raise BackendError(f"cannot reach {self.name} at {self._sdk.base_url}: {e}") from None
        except openai.APIError:
            return ModelCheck()  # not every compatible server lists models; the first call will tell
        if not known:
            return ModelCheck()
        missing = [m for m in models if m not in known]
        return ModelCheck(missing, {m: sorted(k for k in known if k.split("-")[0] in m)[:8] for m in missing})


def _public(message: dict[str, Any]) -> dict[str, Any]:
    out = {k: v for k, v in message.items() if not k.startswith("_")}
    if out.get("tool_calls") == []:
        del out["tool_calls"]
    return out


def _retry_after(e: openai.APIStatusError) -> float | None:
    try:
        return float(e.response.headers.get("retry-after"))
    except (TypeError, ValueError):
        return None
