import json

import pytest

from langtrainer import llm
from langtrainer.config import settings

SCHEMA = {"type": "object", "properties": {"errors": {"type": "array"}}, "required": ["errors"]}


@pytest.fixture
def calls(monkeypatch):
    sent = []
    monkeypatch.setattr(settings, "llm_model", "test-model")
    monkeypatch.setattr(settings, "llm_api_key", "")
    monkeypatch.setattr(settings, "llm_base_url", "")
    return sent


def fake_post(sent, replies):
    def post(url, headers, body, timeout):
        sent.append((url, headers, body))
        reply = replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply

    return post


def chat(content):
    return {"choices": [{"message": {"content": content}}]}


def test_openai_provider_targets_local_server(monkeypatch, calls):
    monkeypatch.setattr(settings, "llm_provider", "openai")
    monkeypatch.setattr(settings, "llm_base_url", "http://localhost:11434/v1/")
    monkeypatch.setattr(llm, "_post_json", fake_post(calls, [chat('{"errors": []}')]))
    assert llm.ask_json("hi", SCHEMA) == {"errors": []}
    url, headers, body = calls[0]
    assert url == "http://localhost:11434/v1/chat/completions"
    assert "Authorization" not in headers
    assert body["model"] == "test-model"
    assert body["response_format"]["type"] == "json_schema"
    assert json.dumps(SCHEMA) in body["messages"][0]["content"]


def test_openai_sends_key_and_falls_back_when_format_unsupported(monkeypatch, calls):
    monkeypatch.setattr(settings, "llm_provider", "openai")
    monkeypatch.setattr(settings, "llm_api_key", "sk-test")
    replies = [llm.LlmError("HTTP 400 from x: no json_schema"), chat('Sure!\n```json\n{"errors": [1]}\n```')]
    monkeypatch.setattr(llm, "_post_json", fake_post(calls, replies))
    assert llm.ask_json("hi", SCHEMA) == {"errors": [1]}
    assert calls[0][1]["Authorization"] == "Bearer sk-test"
    assert [c[2].get("response_format", {}).get("type") for c in calls] == ["json_schema", "json_object"]


def test_openai_other_http_errors_are_not_retried(monkeypatch, calls):
    monkeypatch.setattr(settings, "llm_provider", "openai")
    monkeypatch.setattr(llm, "_post_json", fake_post(calls, [llm.LlmError("HTTP 401 from x: bad key")]))
    with pytest.raises(llm.LlmError, match="401"):
        llm.ask_json("hi", SCHEMA)
    assert len(calls) == 1


def test_missing_required_field_is_reported(monkeypatch, calls):
    monkeypatch.setattr(settings, "llm_provider", "openai")
    monkeypatch.setattr(llm, "_post_json", fake_post(calls, [chat('{"other": 1}')]))
    with pytest.raises(llm.LlmError, match="required"):
        llm.ask_json("hi", SCHEMA)


def test_model_name_is_required_for_api_providers(monkeypatch, calls):
    monkeypatch.setattr(settings, "llm_provider", "openai")
    monkeypatch.setattr(settings, "llm_model", "")
    with pytest.raises(llm.LlmError, match="LT_LLM_MODEL"):
        llm.ask_json("hi", SCHEMA)


def test_anthropic_uses_forced_tool_call(monkeypatch, calls):
    monkeypatch.setattr(settings, "llm_provider", "anthropic")
    monkeypatch.setattr(settings, "llm_api_key", "key")
    reply = {"content": [{"type": "text", "text": "..."}, {"type": "tool_use", "input": {"errors": []}}]}
    monkeypatch.setattr(llm, "_post_json", fake_post(calls, [reply]))
    assert llm.ask_json("hi", SCHEMA) == {"errors": []}
    url, headers, body = calls[0]
    assert url == "https://api.anthropic.com/v1/messages"
    assert headers["x-api-key"] == "key"
    assert body["tool_choice"] == {"type": "tool", "name": "report"}


def test_anthropic_requires_key(monkeypatch, calls):
    monkeypatch.setattr(settings, "llm_provider", "anthropic")
    with pytest.raises(llm.LlmError, match="LT_LLM_API_KEY"):
        llm.ask_json("hi", SCHEMA)


def test_unknown_provider(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "nope")
    with pytest.raises(llm.LlmError, match="Unknown"):
        llm.ask_json("hi", SCHEMA)
