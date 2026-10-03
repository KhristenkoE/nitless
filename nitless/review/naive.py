"""Reviewer: one strong-model call per review unit over the project context, the task, the MR and the diff.

A small change is one unit, so one call sees everything. With TOOLS=on the call may first look things up in
the repository (tools.py), within a fixed budget, before it submits the review.
"""

from importlib import resources

from nitless.diff import FileDiff, render_for_llm
from nitless.llm import LLMClient
from nitless.models import ChangeRequest
from nitless.review.schema import ReviewSubmission
from nitless.review.tools import Toolbox

SYSTEM_PROMPT = resources.files("nitless.prompts").joinpath("review_system.md").read_text()
TOOLS_PROMPT = resources.files("nitless.prompts").joinpath("review_tools.md").read_text()
MAX_TOOL_ROUNDS = 3  # each round resends the whole prompt, so rounds, not calls, drive the cost


def build_user_message(change: ChangeRequest, files: list[FileDiff], profile: str = "", related: str = "",
                       conventions: str = "", task: str = "", scope: str = "") -> str:
    """Project context first (profile, conventions card, related code), then the task, the MR and its diff."""
    description = change.description.strip() or "(no description)"
    return (
        "".join(f"{part}\n\n" for part in (profile, conventions, related, task) if part)
        + f"# Merge request: {change.title}\n\n"
        f"## Description\n{description}\n\n"
        + (f"{scope}\n\n" if scope else "")
        + "## Diff\n"
        "Left column is the new-file line number; `+` added, `-` removed, blank unchanged.\n\n"
        f"{render_for_llm(files)}"
    )


def system_prompt(tools: Toolbox | None) -> str:
    if tools is None:
        return SYSTEM_PROMPT
    return f"{SYSTEM_PROMPT}\n\n{TOOLS_PROMPT.format(calls=tools.max_calls, rounds=MAX_TOOL_ROUNDS)}"


def review(llm: LLMClient, model: str, change: ChangeRequest, files: list[FileDiff],
           profile: str = "", related: str = "", conventions: str = "", task: str = "", scope: str = "",
           tools: Toolbox | None = None) -> ReviewSubmission:
    messages = [
        {"role": "system", "content": system_prompt(tools)},
        {"role": "user", "content": build_user_message(change, files, profile, related, conventions, task, scope)},
    ]
    description = "Submit the review: overall assessment plus zero or more findings."
    if tools is None:
        return llm.call_tool(model, messages, "submit_review", description, ReviewSubmission)
    return llm.run_agent(model, messages, tools, "submit_review", description, ReviewSubmission,
                         max_rounds=MAX_TOOL_ROUNDS)
