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
        "key": "GROQ_API_KEY", "model_var": "GROQ_MODEL", "model": "llama-3.3-70b-versatile",
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


def chat(system: str, user: str, as_json: bool = False) -> str:
    """Send one system + one user message, return the model's text.
    Raises an exception on any failure; the agent catches it and falls back."""
    config = PROVIDERS[provider()]
    body = {
        "model": os.environ.get(config["model_var"]) or config["model"],
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "temperature": 0,  # same question, same answer
    }
    if as_json:
        body["response_format"] = {"type": "json_object"}
    response = requests.post(
        config["url"], json=body, timeout=30,
        headers={"Authorization": f"Bearer {os.environ[config['key']]}"},
    )
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"]


def chat_json(system: str, user: str) -> dict:
    return json.loads(chat(system, user, as_json=True))
