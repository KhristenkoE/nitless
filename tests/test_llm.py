import json
from types import SimpleNamespace

import httpx
import openai
import pytest
from pydantic import BaseModel

from nitless.config import Settings, load_settings
from nitless.errors import ConfigError, LLMError, QuotaExhaustedError
from nitless.llm import LLMClient
from nitless.llm.anthropic_api import AnthropicBackend, from_anthropic, to_anthropic
from nitless.llm.base import (
    BackendError,
    Completion,
    ModelCheck,
    RateLimited,
    ToolCall,
    ToolChoiceRejected,
    is_quota,
    retry_delay_s,
)
from nitless.llm.openai_compat import OpenAICompatBackend

KEYS = ("LLM_PROVIDER", "LLM_API_KEY", "LLM_BASE_URL", "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY",
        "GOOGLE_API_KEY", "OPENROUTER_API_KEY", "GITHUB_TOKEN", "GH_TOKEN", "MODEL_STRONG", "MODEL_FAST",
        "MODEL_VERIFIER", "MR_URL", "LOCAL_REPO", "BASE_REF")


@pytest.fixture(autouse=True)
def clean_env(monkeypatch, tmp_path):
    for var in KEYS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.chdir(tmp_path)  # no .env


def settings(**kw) -> Settings:
    return load_settings(local_repo=".", base_ref="main", **kw)


class Answer(BaseModel):
    verdict: str


# --- configuration --------------------------------------------------------


def test_the_provider_follows_the_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "a")
    s = settings(model_strong="m")
    assert (s.llm_provider, s.llm_key) == ("anthropic", "a")


@pytest.mark.parametrize("key", ["ANTHROPIC_API_KEY", "OPENAI_API_KEY"])
def test_no_provider_has_default_models_and_the_strong_one_is_shared_across_roles(monkeypatch, key):
    monkeypatch.setenv(key, "k")
    with pytest.raises(ConfigError, match="MODEL_STRONG is required"):
        settings()
    s = settings(model_strong="big", model_fast="small")
    assert (s.model_strong, s.model_fast, s.model_verifier) == ("big", "small", "big")


def test_github_models_reuse_the_github_token_and_ollama_needs_no_key(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "g")
    assert settings(llm_provider="github", model_strong="m").llm_key == "g"
    assert settings(llm_provider="ollama", model_strong="qwen3:32b").llm_key == ""


def test_configuration_errors_name_what_to_set():
    with pytest.raises(ConfigError, match="no LLM configured"):
        settings()
    with pytest.raises(ConfigError, match="LLM_BASE_URL is required"):
        settings(llm_provider="openai_compat", model_strong="m")
    with pytest.raises(ConfigError, match="LLM_PROVIDER must be one of"):
        settings(llm_provider="nope", llm_api_key="k")
    with pytest.raises(ConfigError, match="LLM_API_KEY or ANTHROPIC_API_KEY is required"):
        settings(llm_provider="anthropic")
    with pytest.raises(ConfigError, match="MODEL_PRICES entries"):
        settings(anthropic_api_key="k", model_strong="m", model_prices="claude-opus-5-5")


# --- the client -----------------------------------------------------------


class FakeBackend:
    name = "fake"

    def __init__(self, *outcomes, forces=True):
        self.outcomes, self.requests, self.forces = list(outcomes), [], forces

    def forces_tools(self, model):
        return self.forces

    def create(self, model, messages, tools, force, max_tokens):
        self.requests.append({"force": force, "tools": [t.name for t in tools], "messages": messages})
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    def check_models(self, models):
        return ModelCheck(["typo"], {"typo": ["model-a"]}) if "typo" in models else ModelCheck()


def answer(verdict="keep", tokens=(100, 10)) -> Completion:
    call = ToolCall("c1", "submit", json.dumps({"verdict": verdict}))
    return Completion("", [call], {"role": "assistant", "content": None}, *tokens)


def client(backend) -> LLMClient:
    return LLMClient(Settings.model_construct(llm_rate_limit_wait_s=60, llm_max_output_tokens=10), backend=backend)


def test_a_rejected_forced_call_falls_back_to_auto_for_the_rest_of_the_run():
    backend = FakeBackend(ToolChoiceRejected("tool_choice not supported"), answer(), answer())
    llm = client(backend)
    assert llm.call_tool("m", [], "submit", "Answer.", Answer).verdict == "keep"
    llm.call_tool("m", [], "submit", "Answer.", Answer)
    assert [r["force"] for r in backend.requests] == ["submit", None, None]
    assert llm.usage["m"].calls == 2 and llm.usage["m"].prompt_tokens == 200


def test_models_known_to_reject_forcing_are_never_forced():
    backend = FakeBackend(answer(), forces=False)
    client(backend).call_tool("m", [], "submit", "Answer.", Answer)
    assert backend.requests[0]["force"] is None


def test_a_missing_tool_call_is_retried_once_with_the_reason():
    text_only = Completion("I think it is fine.", [], {"role": "assistant", "content": "I think it is fine."})
    backend = FakeBackend(text_only, answer("drop"))
    assert client(backend).call_tool("m", [{"role": "user", "content": "?"}], "submit", "A.", Answer).verdict == "drop"
    assert "no submit call was made" in backend.requests[1]["messages"][-1]["content"]


def test_rate_limits_are_waited_out_but_a_spent_quota_fails_fast(monkeypatch):
    slept = []
    monkeypatch.setattr("nitless.llm.time.sleep", slept.append)
    backend = FakeBackend(RateLimited("slow down", retry_after_s=7), answer())
    client(backend).call_tool("m", [], "submit", "A.", Answer)
    assert slept == [7]
    with pytest.raises(QuotaExhaustedError, match="quota or credit exhausted"):
        client(FakeBackend(RateLimited("credit balance is too low", quota=True))).call_tool("m", [], "s", "A.", Answer)
    with pytest.raises(LLMError, match="still refused m after waiting up to 60s"):
        client(FakeBackend(RateLimited("slow down", retry_after_s=120))).call_tool("m", [], "s", "A.", Answer)


def test_preflight_names_the_missing_model_and_close_matches():
    with pytest.raises(ConfigError, match="'typo' is not available on fake. Similar: model-a"):
        client(FakeBackend()).preflight(["ok", "typo"])


def test_quota_messages_are_told_apart_from_per_minute_limits():
    assert is_quota("Your credit balance is too low to access the Anthropic API")
    assert is_quota('{"code": "insufficient_quota"}')
    assert is_quota("Rate limit of 50 per 86400s exceeded for UserByModelByDay")
    assert not is_quota("Number of request tokens has exceeded your per-minute rate limit")


GEMINI_429 = ("You exceeded your current quota, please check your plan and billing details. "
              "[{'@type': 'type.googleapis.com/google.rpc.QuotaFailure', 'violations': [{'quotaId': '%s'}]}, "
              "{'@type': 'type.googleapis.com/google.rpc.RetryInfo', 'retryDelay': '41s'}]")


def test_gemini_per_minute_limits_are_waited_out_and_per_day_limits_are_a_quota():
    per_minute = GEMINI_429 % "GenerateRequestsPerMinutePerProjectPerModel-FreeTier"
    assert not is_quota(per_minute) and retry_delay_s(per_minute) == 41
    assert is_quota(GEMINI_429 % "GenerateRequestsPerDayPerProjectPerModel-FreeTier")
    assert is_quota("You exceeded your current quota, please check your plan and billing details.")  # OpenAI


def test_an_overloaded_provider_is_waited_out_like_a_rate_limit():
    def server_error(status):
        request = httpx.Request("POST", "https://x/v1/chat/completions")
        return openai.InternalServerError("high demand", response=httpx.Response(status, request=request), body=None)

    def create(**params):
        raise server_error(503)

    backend = OpenAICompatBackend("gemini", "k", None, 1, 0)
    backend._sdk = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    from nitless.llm.base import ToolSpec

    with pytest.raises(RateLimited) as e:
        backend.create("m", [], [ToolSpec("s", "", {})], None, 10)
    assert not e.value.quota and "overloaded (503)" in str(e.value)

    def create_500(**params):
        raise server_error(500)

    backend._sdk.chat.completions.create = create_500
    with pytest.raises(BackendError, match=r"failed \(500\)"):
        backend.create("m", [], [ToolSpec("s", "", {})], None, 10)


# --- Anthropic ------------------------------------------------------------


def test_chat_messages_become_anthropic_turns():
    raw = [{"type": "thinking", "thinking": "hm", "signature": "s"},
           {"type": "tool_use", "id": "t1", "name": "grep", "input": {"pattern": "x"}}]
    system, turns = to_anthropic([
        {"role": "system", "content": "Be strict."},
        {"role": "user", "content": "Review this."},
        {"role": "assistant", "content": None, "_anthropic_content": raw},
        {"role": "tool", "tool_call_id": "t1", "content": "a.py:1: x"},
        {"role": "user", "content": "No more tool calls are available."},
        {"role": "assistant", "content": "ok", "tool_calls": [
            {"id": "t2", "type": "function", "function": {"name": "submit", "arguments": '{"verdict": "keep"}'}}]},
    ])
    assert system == "Be strict."
    assert [t["role"] for t in turns] == ["user", "assistant", "user", "assistant"]
    assert turns[1]["content"] == raw  # thinking goes back unchanged
    assert turns[2]["content"] == [{"type": "tool_result", "tool_use_id": "t1", "content": "a.py:1: x"},
                                   {"type": "text", "text": "No more tool calls are available."}]
    assert turns[3]["content"][1] == {"type": "tool_use", "id": "t2", "name": "submit", "input": {"verdict": "keep"}}


def block(**kw):
    return SimpleNamespace(**kw, model_dump=lambda exclude_none=True: kw)


def test_an_anthropic_message_becomes_a_completion_with_cache_tokens_counted():
    message = SimpleNamespace(
        content=[block(type="thinking", thinking="hm", signature="s"), block(type="text", text="Checking."),
                 block(type="tool_use", id="t1", name="submit", input={"verdict": "keep"})],
        usage=SimpleNamespace(input_tokens=10, cache_read_input_tokens=90, cache_creation_input_tokens=None,
                              output_tokens=5))
    c = from_anthropic(message)
    assert c.text == "Checking." and c.tool_calls == [ToolCall("t1", "submit", '{"verdict": "keep"}')]
    assert (c.prompt_tokens, c.completion_tokens) == (100, 5)
    assert c.assistant_message["_anthropic_content"][0]["type"] == "thinking"


def test_current_claude_models_are_not_forced():
    backend = AnthropicBackend("k", None, 1, 0)
    assert not backend.forces_tools("claude-opus-5-5") and not backend.forces_tools("claude-sonnet-5-5")
    assert backend.forces_tools("claude-haiku-4-5")


# --- chat completions -----------------------------------------------------


def test_chat_completions_requests_drop_private_keys_and_parse_tool_calls():
    sent = {}

    def create(**params):
        sent.update(params)
        call = SimpleNamespace(id="c1", function=SimpleNamespace(name="submit", arguments='{"verdict": "keep"}'))
        message = SimpleNamespace(content=None, tool_calls=[call])
        return SimpleNamespace(choices=[SimpleNamespace(message=message)],
                               usage=SimpleNamespace(prompt_tokens=12, completion_tokens=3))

    backend = OpenAICompatBackend("openai", "k", None, 1, 0)
    backend._sdk = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    from nitless.llm.base import ToolSpec

    c = backend.create("m", [{"role": "assistant", "content": "x", "_anthropic_content": [], "tool_calls": []}],
                       [ToolSpec("submit", "Answer.", {"type": "object"})], "submit", 100)
    assert sent["messages"] == [{"role": "assistant", "content": "x"}]
    assert sent["max_completion_tokens"] == 100 and sent["tool_choice"]["function"]["name"] == "submit"
    assert c.tool_calls[0].name == "submit" and (c.prompt_tokens, c.completion_tokens) == (12, 3)
    assert OpenAICompatBackend("ollama", "", "http://localhost:11434/v1", 1, 0)._max_tokens_param == "max_tokens"
