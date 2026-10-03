"""Command-line entry point. Every flag has an environment-variable equivalent (see README)."""

import argparse
import logging
import sys
from pathlib import Path

from nitless import __version__
from nitless.config import load_settings
from nitless.errors import ReviewerError
from nitless.output import build_adapters
from nitless.pipeline import run


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="nitless",
                                description="AI code review agent for GitLab merge requests and GitHub pull requests.")
    p.add_argument("--version", action="version", version=__version__)
    target = p.add_argument_group("target (MR_URL, or LOCAL_REPO + BASE_REF)")
    target.add_argument("--mr-url", help="GitLab merge request or GitHub pull request URL")
    target.add_argument("--repo-url", help="clone URL, if different from the one derived from --mr-url")
    target.add_argument("--local-repo", type=Path, help="review a local repository instead of a GitLab MR")
    target.add_argument("--base-ref", help="base branch/commit for --local-repo")
    target.add_argument("--head-ref", help="head branch/commit for --local-repo (default HEAD)")
    target.add_argument("--task-source", help="the task: json/yaml/md/txt file or http(s) URL, e.g. a GitLab issue")
    llm = p.add_argument_group("LLM")
    llm.add_argument("--llm-provider", help="anthropic, openai, gemini, github, openrouter, ollama or openai_compat")
    llm.add_argument("--llm-base-url", help="a proxy or self-hosted endpoint (required for openai_compat)")
    llm.add_argument("--model-strong", help="model for review and the requirements check")
    llm.add_argument("--model-fast", help="model for cheap auxiliary steps")
    llm.add_argument("--model-verifier", help="model that verifies every candidate finding")
    tuning = p.add_argument_group("tuning")
    tuning.add_argument("--severity-floor", choices=["critical", "major", "minor", "info"])
    tuning.add_argument("--max-diff-lines", type=int)
    tuning.add_argument("--on-oversize", choices=["fail", "partial"])
    tuning.add_argument("--path-excludes", help="comma-separated gitignore-style patterns")
    tuning.add_argument("--conventions", choices=["on", "off"], help="build the conventions card (default on)")
    tuning.add_argument("--verify", choices=["on", "off"], help="verify every candidate finding (default on)")
    tuning.add_argument("--min-confidence", type=float, help="drop verified findings below this confidence")
    tuning.add_argument("--max-findings", type=int, help="per-MR cap (default: scaled by diff size; 0 = no cap)")
    out = p.add_argument_group("output")
    out.add_argument("--output-adapter", help="comma-separated adapters: json, markdown, gitlab, github")
    out.add_argument("--output-file", type=Path, help="write JSON here instead of stdout")
    out.add_argument("--markdown-file", type=Path, help="write the markdown report here instead of stdout")
    out.add_argument("--gitlab-dry-run", choices=["on", "off"],
                     help="write the notes the gitlab adapter would post to gitlab-notes.json instead of posting")
    out.add_argument("--github-dry-run", choices=["on", "off"],
                     help="write the comments the github adapter would post to github-comments.json instead of posting")
    p.add_argument("--workdir", type=Path, help="keep the checkout here (default: temp dir, removed after run)")
    p.add_argument("--log-level", help="DEBUG, INFO, WARNING, ERROR")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    overrides = vars(parse_args(argv))
    _setup_logging(overrides.get("log_level") or "INFO")
    try:
        settings = load_settings(**overrides)
        _setup_logging(settings.log_level)
        adapters = build_adapters(settings)
    except ReviewerError as e:
        logging.getLogger("nitless").error("%s", e)
        sys.exit(e.exit_code)
    sys.exit(run(settings, adapters))


def _setup_logging(level: str) -> None:
    """Our logs at the requested level; third-party libraries only at WARNING+ unless debugging."""
    logging.basicConfig(stream=sys.stderr, level=logging.WARNING, format="[nitless] %(levelname)s %(message)s",
                        force=True)
    level = level.upper()
    logging.getLogger("nitless").setLevel(level)
    if level == "DEBUG":
        logging.getLogger().setLevel(logging.DEBUG)
