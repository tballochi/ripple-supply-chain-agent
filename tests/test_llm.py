"""Checks on the LLM client, with the HTTP call replaced by a fake."""

import pytest
import requests

from ripple import llm


class FakeResponse:
    def __init__(self, status, payload=None):
        self.status_code, self._payload = status, payload or {}

    def json(self):
        return self._payload


@pytest.fixture
def groq(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    sent = {}

    def install(response):
        def post(url, json, timeout, headers):
            sent.update(url=url, body=json)
            if isinstance(response, Exception):
                raise response
            return response
        monkeypatch.setattr(llm.requests, "post", post)
        return sent
    return install


def test_success_and_reasoning_effort(groq):
    sent = groq(FakeResponse(200, {"choices": [{"message": {"content": "ok"}}]}))
    assert llm.chat("system", "user") == "ok"
    assert sent["body"]["model"] == "openai/gpt-oss-120b"
    assert sent["body"]["reasoning_effort"] == "low" and sent["body"]["temperature"] == 0


def test_rate_limit_gives_a_clear_message(groq):
    groq(FakeResponse(429))
    with pytest.raises(llm.LLMError, match="rate limit"):
        llm.chat("system", "user")


def test_network_error_is_wrapped(groq):
    groq(requests.ConnectionError("down"))
    with pytest.raises(llm.LLMError, match="network error"):
        llm.chat("system", "user")


def test_no_key_means_no_provider():
    assert llm.provider() is None and not llm.available()


def test_key_added_to_env_file_while_running_is_picked_up(monkeypatch, tmp_path):
    monkeypatch.delenv("GROQ_API_KEY")
    monkeypatch.delenv("MISTRAL_API_KEY")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(llm, "load_dotenv", lambda: llm.os.environ.setdefault("GROQ_API_KEY", "from-file"))
    assert llm.provider() == "groq"
