"""Minimal LLM client for Groq or Mistral (both have a free tier).

Both providers expose the same "chat completions" HTTP API, so one small
function covers the two. The key is read from the .env file. With no key,
available() is False and the agent uses its rule-based mode instead.
"""

import json
import os

import requests
from dotenv import load_dotenv

load_dotenv()  # reads .env from the current folder, if present

PROVIDERS = {
    "groq": {
        "url": "https://api.groq.com/openai/v1/chat/completions",
        "key": "GROQ_API_KEY", "model_var": "GROQ_MODEL", "model": "openai/gpt-oss-120b",
    },
    "mistral": {
        "url": "https://api.mistral.ai/v1/chat/completions",
        "key": "MISTRAL_API_KEY", "model_var": "MISTRAL_MODEL", "model": "mistral-small-latest",
    },
}


def provider() -> str | None:
    """Name of the provider to use, or None when no key is configured."""
    forced = os.environ.get("RIPPLE_LLM_PROVIDER", "").lower()
    names = [forced] if forced in PROVIDERS else list(PROVIDERS)
    for name in names:
        if os.environ.get(PROVIDERS[name]["key"]):
            return name
    return None


def available() -> bool:
    return provider() is not None


class LLMError(Exception):
    """An LLM call failed. The message is short and safe to show to the user."""


def chat(system: str, user: str, as_json: bool = False) -> str:
    """Send one system + one user message, return the model's text.
    Raises LLMError on any failure; the agent catches it and falls back."""
    config = PROVIDERS[provider()]
    model = os.environ.get(config["model_var"]) or config["model"]
    body = {
        "model": model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "temperature": 0,  # same question, same answer
        "max_tokens": 1200,
    }
    if model.startswith("openai/gpt-oss"):
        # A reasoning model: keep its hidden reasoning short. Free tiers count
        # those tokens too (Groq's free tier allows 8,000 tokens per minute).
        body["reasoning_effort"] = "low"
    if as_json:
        body["response_format"] = {"type": "json_object"}
    try:
        response = requests.post(
            config["url"], json=body, timeout=30,
            headers={"Authorization": f"Bearer {os.environ[config['key']]}"},
        )
    except requests.RequestException as error:
        raise LLMError(f"network error ({type(error).__name__})") from error
    if response.status_code == 429:
        raise LLMError("rate limit of the free tier reached, try again in a minute")
    if response.status_code >= 400:
        raise LLMError(f"HTTP {response.status_code} from {provider()}")
    return response.json()["choices"][0]["message"]["content"]


def chat_json(system: str, user: str) -> dict:
    return json.loads(chat(system, user, as_json=True))
