import json
import os
import subprocess
from pathlib import Path

import pytest
from pydantic import BaseModel

from nitless.config import Settings
from nitless.context.index import RepoIndex
from nitless.errors import LLMError
from nitless.llm import LLMClient
from nitless.llm.base import Completion, ToolCall
from nitless.review.tools import Toolbox, ToolError, safe_path

FILES = {
    "app/schemas.py": "from pydantic import BaseModel, Field\n\n\nclass CouponCreate(BaseModel):\n"
                      "    percent_off: int = Field(ge=1, le=100)\n",
    "app/orders.py": "from app.schemas import CouponCreate\n\n\ndef apply(c: CouponCreate):\n"
                     "    return c.percent_off\n",
    "README.md": "# Shop\n",
}


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    for path, text in FILES.items():
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_text(text)
    (root / "untracked.txt").write_text("not in git\n")
    (tmp_path / "secret.txt").write_text("outside\n")
    os.symlink(tmp_path / "secret.txt", root / "link.txt")
    git = ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-C", str(root)]
    subprocess.run([*git, "init", "-q"], check=True)
    subprocess.run([*git, "add", "app", "README.md", "link.txt"], check=True)
    subprocess.run([*git, "commit", "-qm", "init"], check=True)
    return root


def toolbox(repo: Path, calls: int = 8, tokens: int = 20000) -> Toolbox:
    return Toolbox(RepoIndex(repo, [*FILES, "link.txt"], "HEAD"), "unit 1", calls, tokens)


def test_paths_outside_the_repository_are_rejected(repo):
    for bad in ("../secret.txt", "/etc/passwd", "app/../../secret.txt", "link.txt", "C:/x"):
        with pytest.raises(ToolError):
            safe_path(repo, bad)
    assert safe_path(repo, "./app//orders.py") == "app/orders.py" and safe_path(repo, ".") == ""

    tools = toolbox(repo)
    for path in ("../secret.txt", "link.txt", "untracked.txt", ".git/config"):
        assert tools.call("read_file", {"path": path}).startswith("error:")
    assert [row["error"] is not None for row in tools.trace] == [True] * 4


def test_tools_read_search_and_find_symbols(repo):
    tools = toolbox(repo)
    assert "     5      percent_off: int = Field(ge=1, le=100)" in tools.call("read_file", {"path": "app/schemas.py",
                                                                                          "start": 4, "end": 5})
    assert "app/schemas.py:5:" in tools.call("grep", {"pattern": "percent_off:", "glob": "*.py"})
    definition = tools.call("find_definition", {"symbol": "CouponCreate"})
    assert definition.startswith("class CouponCreate in app/schemas.py") and "le=100" in definition
    references = tools.call("find_references", {"symbol": "CouponCreate"})
    assert "app/orders.py:4:" in references and "app/schemas.py:4" not in references  # the definition itself
    assert tools.call("list_dir", {"path": ""}).splitlines()[1:] == ["app/ (2 files)", "README.md", "link.txt"]
    assert tools.call("grep", {"pattern": "("}).startswith("error:")
    assert [row["tool"] for row in tools.trace][:2] == ["read_file", "grep"] and tools.trace[0]["unit"] == "unit 1"


def test_budgets_cap_calls_and_result_size(repo):
    tools = toolbox(repo, calls=2)
    tools.call("list_dir", {})
    tools.call("list_dir", {})
    assert tools.exhausted and tools.call("list_dir", {}).startswith("Tool budget exhausted")
    assert len(tools.trace) == 2

    big = toolbox(repo, tokens=250)
    big.call("read_file", {"path": "app/schemas.py"})
    assert big.trace[0]["result_tokens"] <= 250


class Answer(BaseModel):
    verdict: str


def response(*calls: tuple[str, dict], content: str | None = None) -> Completion:
    tool_calls = [ToolCall(f"call_{i}", name, json.dumps(args)) for i, (name, args) in enumerate(calls)]
    return Completion(text=content or "", tool_calls=tool_calls, assistant_message={
        "role": "assistant", "content": content, "tool_calls": [
            {"id": c.id, "type": "function", "function": {"name": c.name, "arguments": c.arguments}}
            for c in tool_calls]})


class ScriptedBackend:
    """A model that follows a script of responses; every request is recorded."""

    name = "scripted"

    def __init__(self, script):
        self.script, self.requests = list(script), []

    def forces_tools(self, model):
        return True

    def create(self, model, messages, tools, force, max_tokens):
        self.requests.append({"messages": list(messages), "tools": [t.name for t in tools], "force": force})
        return self.script.pop(0)


def ScriptedClient(script) -> LLMClient:
    llm = LLMClient(Settings.model_construct(llm_rate_limit_wait_s=0, llm_max_output_tokens=10),
                    backend=ScriptedBackend(script))
    llm.requests = llm.backend.requests
    return llm


def test_the_agent_loop_runs_tools_then_returns_the_submitted_answer(repo):
    tools = toolbox(repo)
    llm = ScriptedClient([
        response(("find_definition", {"symbol": "CouponCreate"}), ("grep", {"pattern": "percent_off"})),
        response(("submit", {"verdict": "drop"})),
    ])
    answer = llm.run_agent("m", [{"role": "user", "content": "Is it a bug?"}], tools, "submit", "Answer.", Answer,
                           max_rounds=3)
    assert answer.verdict == "drop" and [row["tool"] for row in tools.trace] == ["find_definition", "grep"]
    second = llm.requests[1]
    assert [m["role"] for m in second["messages"]] == ["user", "assistant", "tool", "tool"]
    assert "le=100" in second["messages"][2]["content"] and second["force"] is None
    assert set(second["tools"]) >= {"read_file", "submit"}
    assert llm.usage_by_tool["submit"].calls == 2


def test_the_agent_must_answer_once_the_budget_is_spent(repo):
    tools = toolbox(repo, calls=1)
    llm = ScriptedClient([
        response(("list_dir", {}), ("list_dir", {"path": "app"})),  # the second call is over budget
        response(content="Let me think."),  # no answer: nudged
        response(("submit", {"verdict": "keep"})),
    ])
    assert llm.run_agent("m", [{"role": "user", "content": "?"}], tools, "submit", "Answer.", Answer,
                         max_rounds=3).verdict == "keep"
    assert len(tools.trace) == 1
    assert "Tool budget exhausted" in llm.requests[1]["messages"][3]["content"]
    last = llm.requests[-1]
    assert last["tools"] == ["submit"] and last["force"] == "submit"  # only the answer tool is offered
    assert "No more tool calls" in last["messages"][-3]["content"]


def test_the_agent_fails_without_a_valid_answer(repo):
    llm = ScriptedClient([response(("submit", {"wrong": 1}))] * 3)
    with pytest.raises(LLMError, match="did not return a valid submit call"):
        llm.run_agent("m", [{"role": "user", "content": "?"}], toolbox(repo), "submit", "Answer.", Answer,
                      max_rounds=1)
