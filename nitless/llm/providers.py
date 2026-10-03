"""Provider presets: where each one lives and which key it reads."""

from dataclasses import dataclass

from nitless.llm.anthropic_api import AnthropicBackend
from nitless.llm.base import Backend
from nitless.llm.openai_compat import OpenAICompatBackend


@dataclass(frozen=True)
class Provider:
    name: str
    base_url: str | None  # None: the SDK's default
    key_field: str | None  # the Settings field holding its key when LLM_API_KEY is unset
    needs_key: bool = True
    native: bool = False  # the Anthropic SDK rather than chat completions


PROVIDERS: dict[str, Provider] = {p.name: p for p in [
    Provider("anthropic", None, "anthropic_api_key", native=True),
    Provider("openai", None, "openai_api_key"),
    Provider("gemini", "https://generativelanguage.googleapis.com/v1beta/openai/", "gemini_api_key"),
    Provider("github", "https://models.github.ai/inference", "github_token"),
    Provider("openrouter", "https://openrouter.ai/api/v1", "openrouter_api_key"),
    Provider("ollama", "http://localhost:11434/v1", None, needs_key=False),
    Provider("openai_compat", None, "openai_api_key", needs_key=False),  # set LLM_BASE_URL
]}

# LLM_PROVIDER unset: the first provider whose key is present.
AUTODETECT = ("anthropic", "openai", "gemini", "openrouter")


def make_backend(provider: str, api_key: str, base_url: str | None, timeout_s: float, max_retries: int) -> Backend:
    preset = PROVIDERS[provider]
    url = base_url or preset.base_url
    if preset.native:
        return AnthropicBackend(api_key, url, timeout_s, max_retries)
    return OpenAICompatBackend(provider, api_key, url, timeout_s, max_retries)
