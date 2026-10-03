import json
import subprocess
from pathlib import Path

import httpx
import pytest
from pydantic import SecretStr

from nitless.context import intent as intent_mod
from nitless.context.intent import (
    TaskDocument,
    find_story_file,
    load_task_source,
    mr_document,
    parse_intent,
)
from nitless.errors import LLMError, TaskSourceError
from nitless.models import ChangeRequest


class FakeLLM:
    """Stands in for LLMClient.call_tool; records what it was asked."""

    def __init__(self, answer=None, error: Exception | None = None):
        self.answer, self.error, self.calls = answer, error, []

    def call_tool(self, model, messages, tool_name, tool_description, schema, max_tokens=None):
        self.calls.append(messages[-1]["content"])
        if self.error:
            raise self.error
        return schema.model_validate(self.answer)


def change(title="Add cancel endpoint", description="") -> ChangeRequest:
    return ChangeRequest(provider="local", repo="r", ref="main..x", title=title, description=description,
                         base_sha="a", start_sha="a", head_sha="b")


def test_structured_json_with_aliases_maps_without_llm(tmp_path):
    path = tmp_path / "task.json"
    path.write_text(json.dumps({
        "key": "ORD-7", "summary": "Cancel orders", "description": "Customers cancel unpaid orders.",
        "acceptanceCriteria": ["POST /orders/{id}/cancel returns 200", {"text": "Paid orders return 409"}],
        "nonGoals": "- Refunds\n- Restocking",
    }))
    llm = FakeLLM()
    intent = parse_intent(load_task_source(str(path)), llm, "fast")
    assert llm.calls == []
    assert intent.kind == "explicit" and intent.parsed_by == "structured"
    assert intent.title == "ORD-7: Cancel orders"
    assert intent.intent == "Customers cancel unpaid orders."
    assert intent.acceptance_criteria == ["POST /orders/{id}/cancel returns 200", "Paid orders return 409"]
    assert intent.out_of_scope == ["Refunds", "Restocking"]
    assert intent.assessable
    assert "- AC2: Paid orders return 409" in intent.render() and "Do not report" in intent.render()


def test_yaml_with_string_criteria_and_jira_fields(tmp_path):
    path = tmp_path / "story.yaml"
    path.write_text("fields:\n  summary: Low stock report\n  goal: Reorder in one call\n"
                    "ac: |\n  1. Sorted lowest first\n  2) Threshold defaults to 10\n"
                    "out-of-scope:\n  - Pagination\n")
    intent = parse_intent(load_task_source(str(path)), None, "fast")
    assert intent.title == "Low stock report" and intent.intent == "Reorder in one call"
    assert intent.acceptance_criteria == ["Sorted lowest first", "Threshold defaults to 10"]
    assert intent.out_of_scope == ["Pagination"]


def test_markdown_goes_to_the_fast_model_and_invented_criteria_are_dropped(tmp_path):
    path = tmp_path / "TICKET.md"
    path.write_text("# BK-301 Price quotes\n\nShow the price before booking.\n\n## Acceptance criteria\n"
                    "- Ranges longer than maxDurationMinutes are rejected with 422\n\n## Out of scope\n- Discounts\n")
    llm = FakeLLM({"title": "BK-301 Price quotes", "intent": "Show the price before booking.",
                   "acceptance_criteria": ["Ranges longer than maxDurationMinutes are rejected with 422",
                                           "Responses are cached in Redis for five minutes"],
                   "out_of_scope": ["Discounts"]})
    intent = parse_intent(load_task_source(str(path)), llm, "fast")
    assert len(llm.calls) == 1 and "maxDurationMinutes" in llm.calls[0]
    assert intent.parsed_by == "llm" and intent.title == "BK-301 Price quotes"
    assert intent.acceptance_criteria == ["Ranges longer than maxDurationMinutes are rejected with 422"]
    assert intent.out_of_scope == ["Discounts"]


def test_explicit_source_problems_fail_loudly(tmp_path):
    with pytest.raises(TaskSourceError, match="not found"):
        load_task_source(str(tmp_path / "missing.json"))
    (tmp_path / "bad.json").write_text("{nope")
    with pytest.raises(TaskSourceError, match="not valid JSON"):
        load_task_source(str(tmp_path / "bad.json"))
    (tmp_path / "empty.md").write_text("  \n")
    with pytest.raises(TaskSourceError, match="empty"):
        load_task_source(str(tmp_path / "empty.md"))
    doc = TaskDocument("t.md", "explicit", "# Task\n\nDo things.")
    with pytest.raises(LLMError):
        parse_intent(doc, FakeLLM(error=LLMError("quota")), "fast")


def test_gitlab_issue_is_read_through_the_api(monkeypatch):
    seen = {}

    def fake_get(url, headers=None, timeout=None, **_):
        seen["url"], seen["headers"] = url, headers
        return httpx.Response(200, json={"title": "Cancel orders", "description": "## Acceptance criteria\n- x"},
                              request=httpx.Request("GET", url))

    monkeypatch.setattr(intent_mod.httpx, "get", fake_get)
    doc = load_task_source("https://git.example.com/shop/orders/-/issues/42", SecretStr("tok"),
                           mr_url="https://git.example.com/shop/orders/-/merge_requests/7")
    assert seen["url"] == "https://git.example.com/api/v4/projects/shop%2Forders/issues/42"
    assert seen["headers"] == {"PRIVATE-TOKEN": "tok"}
    assert doc.text.startswith("# Cancel orders") and doc.kind == "explicit"

    load_task_source("https://other.example.com/g/p/-/work_items/3", SecretStr("tok"),
                     mr_url="https://git.example.com/shop/orders/-/merge_requests/7")
    assert seen["headers"] == {}  # the token never goes to another host

    monkeypatch.setattr(intent_mod.httpx, "get", lambda url, **_: httpx.Response(
        404, request=httpx.Request("GET", url)))
    with pytest.raises(TaskSourceError, match="not accessible"):
        load_task_source("https://git.example.com/shop/orders/-/issues/9", SecretStr("tok"))


def commit(root: Path, base: dict[str, str], head: dict[str, str]) -> list[str]:
    """Commit `base`, then `head` on top; return the paths `head` changed."""
    git = ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-C", str(root)]
    subprocess.run([*git, "init", "-q"], check=True)
    for files in (base, head):
        for path, text in files.items():
            (root / path).parent.mkdir(parents=True, exist_ok=True)
            (root / path).write_text(text)
        subprocess.run([*git, "add", "-A"], check=True)
        subprocess.run([*git, "commit", "-qm", "c", "--allow-empty"], check=True)
    return list(head)


def test_story_file_discovery_prefers_changed_then_root(tmp_path):
    story = json.dumps({"title": "T", "intent": "I", "acceptance_criteria": ["a"]})
    changed = commit(tmp_path, {"task.json": story, "server/app.ts": "x"},
                     {"server/TASK.md": "# Server task", "story.json": story, "server/app.ts": "y"})
    doc = find_story_file(tmp_path, changed)
    assert doc.path == "story.json" and doc.kind == "repo" and doc.data["title"] == "T"

    # a story file this change touches beats an older one at the root
    doc = find_story_file(tmp_path, ["server/TASK.md", "server/app.ts"])
    assert doc.path == "server/TASK.md" and doc.data is None
    # nothing changed: the root story committed before the MR is still the task
    assert find_story_file(tmp_path, ["server/app.ts"]).path == "story.json"


def test_mr_description_is_only_extracted_when_it_states_criteria():
    llm = FakeLLM({"acceptance_criteria": ["Paid orders return 409"], "out_of_scope": ["Refunds"]})
    plain = parse_intent(mr_document(change(description="Adds the endpoint and tests.")), llm, "fast")
    assert llm.calls == [] and plain.kind == "mr" and plain.parsed_by == "none"
    assert not plain.assessable and plain.render() == ""

    described = change(description="Adds it.\n\n## Acceptance criteria\n- [ ] Paid orders return 409\n\n"
                                   "Refunds are out of scope.")
    intent = parse_intent(mr_document(described), llm, "fast")
    assert len(llm.calls) == 1 and intent.kind == "mr" and intent.parsed_by == "llm"
    assert intent.acceptance_criteria == ["Paid orders return 409"] and intent.assessable
    assert "Acceptance criteria" in intent.render() and "## Add cancel endpoint" not in intent.render()

    degraded = parse_intent(mr_document(described), FakeLLM(error=LLMError("down")), "fast")
    assert degraded.parsed_by == "none" and degraded.acceptance_criteria == []


def test_pipeline_exits_5_on_a_missing_task_source(tmp_path, monkeypatch):
    from nitless import pipeline
    from nitless.config import load_settings

    class NoNetworkClient:
        usage, usage_by_tool = {}, {}

        def __init__(self, settings):
            pass

        def preflight(self, models):
            pass

    monkeypatch.setattr(pipeline, "LLMClient", NoNetworkClient)
    settings = load_settings(local_repo=tmp_path, base_ref="main", anthropic_api_key="k", model_strong="m",
                             task_source=str(tmp_path / "nope.json"))
    assert pipeline.run(settings, []) == 5
