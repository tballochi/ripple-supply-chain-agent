"""Retrieval quality must not regress (see ripple/evaluate.py)."""

import pytest

from ripple import embeddings, evaluate


def total(by_category):
    ok = sum(v[0] for v in by_category.values())
    return ok / sum(v[1] for v in by_category.values())


def test_full_text_fallback_stays_good(monkeypatch):
    # The mode used when the embedding model is unavailable (and in CI).
    monkeypatch.setenv("RIPPLE_NO_EMBEDDINGS", "1")
    scores = evaluate.run()["scores"]
    assert total(scores["+ full-text"]) >= 0.85
    assert total(scores["+ full-text"]) > total(scores["names only"])
    assert scores["names only"]["off-topic"] == (6, 6) and scores["+ full-text"]["off-topic"] == (6, 6)


@pytest.mark.skipif(embeddings.embed(["probe"]) is None, reason="embedding model not available")
def test_hybrid_is_never_worse_than_one_side():
    scores = evaluate.run()["scores"]
    for setup in ("names only", "+ full-text", "+ vector"):
        assert total(scores["hybrid"]) >= total(scores[setup])
    assert total(scores["hybrid"]) >= 0.95
