"""The prompts. A repository may replace a system prompt with `.nitless/prompts/<name>.md` (`nitless.repo_config`).

The tool prompts are templates filled in by the code, so only the system prompts can be replaced.
"""

from functools import cache
from importlib import resources

PROMPT_NAMES = ("conventions_system", "intent_system", "requirements_system", "review_system", "verifier_system")
_overrides: dict[str, str] = {}


@cache
def default(name: str) -> str:
    return resources.files(__name__).joinpath(f"{name}.md").read_text()


def get(name: str) -> str:
    """The prompt for this run: the repository's replacement if it set one, else the built-in text."""
    return _overrides.get(name) or default(name)


def override(prompts: dict[str, str]) -> None:
    """Replace system prompts for the current run; an empty mapping restores the built-in ones."""
    unknown = set(prompts) - set(PROMPT_NAMES)
    if unknown:
        raise ValueError(f"no such prompt: {', '.join(sorted(unknown))}")
    _overrides.clear()
    _overrides.update(prompts)
