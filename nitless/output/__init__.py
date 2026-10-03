"""Output adapter registry. Adding an adapter = one module + one line in ADAPTERS."""

from nitless.config import Settings
from nitless.errors import ConfigError
from nitless.output.base import OutputAdapter
from nitless.output.github_review import GitHubReviewAdapter
from nitless.output.gitlab_notes import GitLabNotesAdapter
from nitless.output.json_out import JsonAdapter
from nitless.output.markdown import MarkdownAdapter

ADAPTERS: dict[str, type[OutputAdapter]] = {
    JsonAdapter.name: JsonAdapter,
    MarkdownAdapter.name: MarkdownAdapter,
    GitLabNotesAdapter.name: GitLabNotesAdapter,
    GitHubReviewAdapter.name: GitHubReviewAdapter,
}


def build_adapters(settings: Settings) -> list[OutputAdapter]:
    unknown = [n for n in settings.output_adapter if n not in ADAPTERS]
    if unknown:
        raise ConfigError(f"unknown OUTPUT_ADAPTER {', '.join(unknown)}; available: {', '.join(ADAPTERS)}")
    if not settings.output_adapter:
        raise ConfigError("OUTPUT_ADAPTER is empty")
    adapters = [ADAPTERS[name](settings) for name in dict.fromkeys(settings.output_adapter)]
    for adapter in adapters:
        adapter.validate()
    return adapters


__all__ = ["ADAPTERS", "OutputAdapter", "build_adapters"]
