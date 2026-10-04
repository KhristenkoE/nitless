"""Per-repository configuration: `.nitless.yml` and `.nitless/prompts/<name>.md` in the reviewed repository.

Both are read at the change's base commit, never its head: a pull request cannot loosen its own review, and
a change to the file takes effect once it is merged. The file holds review behaviour only; models, keys and
output belong to the environment. Environment and flags win over the file, the file wins over defaults;
excludes from both apply.
"""

import logging
import posixpath
from pathlib import Path
from typing import Literal

import pathspec
import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from nitless.config import Settings
from nitless.errors import ConfigError
from nitless.git import GitError, run_git
from nitless.models import Category, Severity
from nitless.prompts import PROMPT_NAMES

log = logging.getLogger(__name__)

CONFIG_FILES = (".nitless.yml", ".nitless.yaml")
PROMPTS_DIR = ".nitless/prompts"
# File keys that map one to one onto a setting of the same name.
SETTINGS_KEYS = ("severity_floor", "min_confidence", "max_findings", "verify", "conventions", "tools",
                 "stale_comments")
MAX_INSTRUCTIONS_CHARS = 4000
MAX_RULES = 30


class TeamRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rule: str = Field(min_length=1, max_length=300)
    paths: list[str] = Field(default_factory=list)  # gitignore-style globs; empty: everywhere

    def applies_to(self, paths: list[str]) -> bool:
        if not self.paths:
            return True
        spec = pathspec.PathSpec.from_lines("gitignore", self.paths)
        return any(spec.match_file(p) for p in paths)


class RepoConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    severity_floor: Severity | None = None
    min_confidence: float | None = Field(default=None, ge=0, le=1)
    max_findings: int | None = Field(default=None, ge=0)
    verify: bool | None = None
    conventions: bool | None = None
    tools: bool | None = None
    stale_comments: Literal["resolve", "delete", "keep"] | None = None
    exclude: list[str] = Field(default_factory=list)
    ignore_categories: list[Category] = Field(default_factory=list)
    instructions: str = Field(default="", max_length=MAX_INSTRUCTIONS_CHARS)
    rules: list[TeamRule] = Field(default_factory=list, max_length=MAX_RULES)

    source: str = Field(default="", exclude=True)  # the file it came from
    prompts: dict[str, str] = Field(default_factory=dict, exclude=True)  # prompt name -> replacement text

    @field_validator("rules", mode="before")
    @classmethod
    def _plain_rules(cls, value: object) -> object:
        """A rule may be a bare string: `- Money is Decimal, never float`."""
        if isinstance(value, list):
            return [{"rule": r} if isinstance(r, str) else r for r in value]
        return value

    def guidance(self, paths: list[str]) -> str:
        """The team's instructions and the rules that apply to `paths`, as a prompt section; "" when none."""
        rules = [r for r in self.rules if r.applies_to(paths)]
        if not self.instructions.strip() and not rules:
            return ""
        parts = [f"# Team guidance\n\nFrom the repository maintainers ({self.source}). These are binding for this "
                 "team, like documented rules."]
        if self.instructions.strip():
            parts.append(f"## Instructions\n{self.instructions.strip()}")
        if rules:
            parts.append("## Rules\n" + "\n".join(
                f"- {r.rule}" + (f" (applies to {', '.join(r.paths)})" if r.paths else "") for r in rules))
        return "\n\n".join(parts)

    def trace(self) -> dict:
        return {"source": self.source or None, "settings": self.model_dump(exclude_defaults=True,
                                                                         exclude={"instructions", "rules"}),
                "instructions_chars": len(self.instructions), "rules": len(self.rules),
                "prompts": sorted(self.prompts)}


def load(repo_dir: Path, base_sha: str) -> RepoConfig:
    """The repository's config at `base_sha`; an empty config when there is none. A broken file is a ConfigError."""
    cfg = RepoConfig()
    for name in CONFIG_FILES:
        text = _show(repo_dir, base_sha, name)
        if text is None:
            continue
        try:
            data = yaml.safe_load(text) or {}
        except yaml.YAMLError as e:
            raise ConfigError(f"{name} at {base_sha[:8]} is not valid YAML: {e}") from None
        if not isinstance(data, dict):
            raise ConfigError(f"{name} at {base_sha[:8]} must be a mapping of settings")
        try:
            cfg = RepoConfig.model_validate(data)
        except ValidationError as e:
            problems = "\n".join(f"  - {'.'.join(str(p) for p in err['loc']) or name}: {err['msg']}"
                                 for err in e.errors())
            raise ConfigError(f"invalid {name} at {base_sha[:8]}:\n{problems}") from None
        cfg.source = name
        break
    for prompt in PROMPT_NAMES:
        text = _show(repo_dir, base_sha, posixpath.join(PROMPTS_DIR, f"{prompt}.md"))
        if text is not None and text.strip():
            cfg.prompts[prompt] = text
    if cfg.source or cfg.prompts:
        log.info("repository config: %s%s", cfg.source or "no settings file",
                 f", prompt overrides: {', '.join(sorted(cfg.prompts))}" if cfg.prompts else "")
    return cfg


def apply(settings: Settings, cfg: RepoConfig) -> Settings:
    """Settings with the file's values where the environment left the default; excludes from both."""
    explicit = settings.model_fields_set
    update: dict[str, object] = {key: getattr(cfg, key) for key in SETTINGS_KEYS
                                 if getattr(cfg, key) is not None and key not in explicit}
    if cfg.exclude:
        update["path_excludes"] = [*settings.path_excludes, *cfg.exclude]
    if cfg.ignore_categories:
        update["ignore_categories"] = sorted({*settings.ignore_categories, *cfg.ignore_categories})
    return settings.model_copy(update=update) if update else settings


def _show(repo_dir: Path, sha: str, path: str) -> str | None:
    try:
        return run_git(["show", f"{sha}:{path}"], cwd=repo_dir)
    except GitError:
        return None  # not in that commit
