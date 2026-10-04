import subprocess
from pathlib import Path

import pytest

from nitless import prompts, repo_config
from nitless.config import load_settings
from nitless.errors import ConfigError

CONFIG = """
severity_floor: major
min_confidence: 0.8
stale_comments: keep
exclude: [docs/]
ignore_categories: [test-coverage]
instructions: Focus on money handling.
rules:
  - Money is Decimal, never float
  - rule: Handlers return Result, never raise
    paths: ["app/api/**"]
"""


@pytest.fixture(autouse=True)
def clean_env(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)  # no stray .env
    for var in ("MR_URL", "LOCAL_REPO", "SEVERITY_FLOOR", "MIN_CONFIDENCE", "PATH_EXCLUDES", "IGNORE_CATEGORIES",
                "STALE_COMMENTS"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    monkeypatch.setenv("MODEL_STRONG", "m")
    yield
    prompts.override({})


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True).stdout.strip()


def commit(repo: Path, files: dict[str, str]) -> str:
    for name, text in files.items():
        (repo / name).parent.mkdir(parents=True, exist_ok=True)
        (repo / name).write_text(text)
    git(repo, "add", "-A")
    git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "c")
    return git(repo, "rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path) -> Path:
    path = tmp_path / "repo"
    path.mkdir()
    git(path, "init", "-q")
    return path


def settings(tmp_path, **overrides):
    return load_settings(local_repo=tmp_path, base_ref="main", **overrides)


def test_the_file_is_read_at_the_base_commit_not_the_head(repo):
    base = commit(repo, {".nitless.yml": CONFIG})
    commit(repo, {".nitless.yml": "severity_floor: info\n"})  # the pull request loosening its own review

    cfg = repo_config.load(repo, base)
    assert cfg.source == ".nitless.yml"
    assert (cfg.severity_floor, cfg.min_confidence, cfg.exclude) == ("major", 0.8, ["docs/"])
    assert [r.rule for r in cfg.rules] == ["Money is Decimal, never float", "Handlers return Result, never raise"]


def test_no_file_is_an_empty_config(repo):
    cfg = repo_config.load(repo, commit(repo, {"a.py": "x = 1\n"}))
    assert cfg == repo_config.RepoConfig()
    assert cfg.guidance(["a.py"]) == ""


def test_environment_wins_over_the_file_and_the_file_over_defaults(repo, tmp_path, monkeypatch):
    monkeypatch.setenv("SEVERITY_FLOOR", "critical")
    monkeypatch.setenv("PATH_EXCLUDES", "vendor/")
    cfg = repo_config.load(repo, commit(repo, {".nitless.yml": CONFIG}))
    s = repo_config.apply(settings(tmp_path), cfg)

    assert s.severity_floor == "critical"  # set in the environment
    assert (s.min_confidence, s.stale_comments) == (0.8, "keep")  # defaults replaced by the file
    assert s.path_excludes == ["vendor/", "docs/"]  # both apply
    assert s.ignore_categories == ["test-coverage"]


def test_rules_apply_to_their_paths(repo):
    cfg = repo_config.load(repo, commit(repo, {".nitless.yml": CONFIG}))

    everywhere = cfg.guidance(["app/models.py"])
    assert everywhere.startswith("# Team guidance\n\nFrom the repository maintainers (.nitless.yml).")
    assert "## Instructions\nFocus on money handling." in everywhere
    assert "- Money is Decimal, never float" in everywhere and "Handlers return Result" not in everywhere
    assert "- Handlers return Result, never raise (applies to app/api/**)" in cfg.guidance(["app/api/refunds.py"])


@pytest.mark.parametrize(("text", "message"), [
    ("severity_floor: [", "not valid YAML"),
    ("- a list\n", "must be a mapping"),
    ("model_strong: gpt\n", "model_strong: Extra inputs are not permitted"),
    ("ignore_categories: [style]\n", "ignore_categories.0"),
    ("min_confidence: 2\n", "min_confidence: Input should be less than or equal to 1"),
])
def test_a_broken_file_is_a_config_error_naming_the_problem(repo, text, message):
    base = commit(repo, {".nitless.yml": text})
    with pytest.raises(ConfigError, match=rf"(?s)\.nitless\.yml at {base[:8]}.*{message}"):
        repo_config.load(repo, base)


def test_prompt_overrides_replace_system_prompts_for_the_run(repo):
    base = commit(repo, {".nitless/prompts/review_system.md": "Review like a pirate.\n",
                         ".nitless/prompts/review_tools.md": "{not a template}"})  # tool prompts stay built in
    cfg = repo_config.load(repo, base)
    assert cfg.prompts == {"review_system": "Review like a pirate.\n"}

    prompts.override(cfg.prompts)
    assert prompts.get("review_system") == "Review like a pirate.\n"
    assert prompts.get("verifier_system") == prompts.default("verifier_system")
    prompts.override({})
    assert prompts.get("review_system") == prompts.default("review_system")


def test_ignore_categories_from_the_environment_are_checked(tmp_path, monkeypatch):
    monkeypatch.setenv("IGNORE_CATEGORIES", "convention, style")
    with pytest.raises(ConfigError, match="unknown categories style"):
        settings(tmp_path)
