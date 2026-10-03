import pytest

from nitless.config import load_settings
from nitless.errors import ConfigError
from nitless.output import build_adapters
from nitless.scm.gitlab import parse_mr_url


@pytest.fixture(autouse=True)
def clean_env(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)  # no stray .env
    for var in ("MR_URL", "LOCAL_REPO", "BASE_REF", "ANTHROPIC_API_KEY", "MODEL_STRONG", "OUTPUT_ADAPTER",
                "GITLAB_TOKEN"):
        monkeypatch.delenv(var, raising=False)


def test_parse_mr_url_with_subgroups():
    ref = parse_mr_url("https://gitlab.example.com/group/sub/proj/-/merge_requests/42/diffs")
    assert (ref.base_url, ref.project, ref.iid) == ("https://gitlab.example.com", "group/sub/proj", 42)


def test_parse_mr_url_rejects_other_urls():
    with pytest.raises(ConfigError):
        parse_mr_url("https://gitlab.example.com/group/proj/-/issues/1")


def test_missing_config_lists_every_problem():
    with pytest.raises(ConfigError) as exc:
        load_settings()
    assert "MR_URL" in str(exc.value)


def test_env_lists_are_comma_separated(monkeypatch):
    monkeypatch.setenv("MR_URL", "https://h/g/p/-/merge_requests/1")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    monkeypatch.setenv("MODEL_STRONG", "m")
    monkeypatch.setenv("OUTPUT_ADAPTER", "json, json")
    monkeypatch.setenv("PATH_EXCLUDES", "gen/,*.pb")
    settings = load_settings()
    assert settings.output_adapter == ["json", "json"]
    assert settings.excludes[-2:] == ["gen/", "*.pb"]
    assert len(build_adapters(settings)) == 1


def test_unknown_adapter_fails_before_work(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    monkeypatch.setenv("MODEL_STRONG", "m")
    settings = load_settings(mr_url="https://h/g/p/-/merge_requests/1", output_adapter="slack")
    with pytest.raises(ConfigError, match="unknown OUTPUT_ADAPTER slack"):
        build_adapters(settings)
