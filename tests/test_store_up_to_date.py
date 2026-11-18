"""The committed store must be exactly what the generator produces.

If this fails, someone changed ripple/generate.py without regenerating:
run `python -m ripple.generate` and commit data/.
"""

import json

from ripple import db, generate

STORE_FILES = ["graph.json", ".cypherlite/schema/schema.cypher"]


def test_regenerated_store_matches_the_committed_one(tmp_path, monkeypatch):
    # The vectors come from data/alert_embeddings.json: no model needed.
    monkeypatch.setenv("RIPPLE_NO_EMBEDDINGS", "1")
    cache_before = generate.VECTOR_CACHE.read_text()
    fresh = tmp_path / "ripple.relate"
    generate.load(generate.build_dataset(), path=fresh)

    assert generate.VECTOR_CACHE.read_text() == cache_before, "vector cache is stale"
    for name in STORE_FILES:
        committed = (db.STORE_PATH / name).read_text()
        regenerated = (fresh / name).read_text()
        if name.endswith(".json"):
            committed, regenerated = json.loads(committed), json.loads(regenerated)
        assert regenerated == committed, f"{name} differs: run python -m ripple.generate"
