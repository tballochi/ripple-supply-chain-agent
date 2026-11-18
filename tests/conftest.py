"""Shared test setup."""

import pytest


@pytest.fixture(autouse=True)
def isolated_workspace(monkeypatch, tmp_path_factory):
    """Tests write plans and memory to a temporary workspace, never to .ripple/."""
    monkeypatch.setenv("RIPPLE_WORKSPACE", str(tmp_path_factory.mktemp("ws") / "workspace.relate"))


@pytest.fixture(autouse=True)
def no_real_llm(monkeypatch):
    """Tests never call a real LLM, even if a local .env holds a key.
    Tests that need the LLM path replace it with a fake."""
    for key in ("GROQ_API_KEY", "MISTRAL_API_KEY", "RIPPLE_LLM_PROVIDER"):
        monkeypatch.setenv(key, "")
