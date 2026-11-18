"""The embedding model must fail fast and quietly when it cannot be loaded."""

import time

from ripple import embeddings


def reset(monkeypatch, tmp_path):
    monkeypatch.setattr(embeddings, "_model", None)
    monkeypatch.setattr(embeddings, "_unavailable", False)
    monkeypatch.setattr(embeddings, "CACHE_DIR", tmp_path / "empty-cache")
    monkeypatch.delenv("RIPPLE_NO_EMBEDDINGS", raising=False)


def test_offline_fallback_is_fast_quiet_and_cached(monkeypatch, tmp_path, capsys):
    reset(monkeypatch, tmp_path)
    attempts = []

    def no_network():
        attempts.append(1)
        raise ConnectionError("no network")

    monkeypatch.setattr(embeddings, "_download_once", no_network)
    started = time.time()
    assert embeddings.embed(["typhoon"]) is None
    assert embeddings.embed(["strike"]) is None
    assert time.time() - started < 5
    assert len(attempts) == 1                  # tried once for the whole process
    err = capsys.readouterr().err
    assert err.count("[ripple]") == 1 and "--download" in err


def test_switch_off_with_environment_variable(monkeypatch):
    monkeypatch.setenv("RIPPLE_NO_EMBEDDINGS", "1")
    assert embeddings.embed(["anything"]) is None
