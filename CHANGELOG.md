# Changelog

## 0.2.0

- Any LLM provider: Anthropic through its own SDK, and OpenAI, Gemini, GitHub Models, OpenRouter, Ollama or any chat-completions server through `LLM_PROVIDER` and `LLM_BASE_URL`.
- Cost from list prices, with `MODEL_PRICES` for models without a built-in price.
- A spent quota or credit on any provider fails fast with exit code 7; per-minute limits are waited out.
- GitHub pull requests: inline review comments and a summary comment, alongside GitLab merge requests.
- Renamed to nitless.

## 0.1.0

- The review pipeline: project profile, symbol graph, task intent and requirements check, conventions card, triage and review units, adversarial verifier, JSON, Markdown and GitLab output, and the eval harness.
