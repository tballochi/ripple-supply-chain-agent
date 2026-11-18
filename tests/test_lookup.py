"""Checks on the safety of LLM-written Cypher (no LLM involved)."""

import pytest

from ripple import db, lookup


@pytest.fixture(scope="module")
def conn():
    connection = db.connect()
    yield connection
    connection.close()


def test_a_read_query_passes(conn):
    lookup.check(conn, "MATCH (p:Port) RETURN p.name AS name LIMIT 5")


@pytest.mark.parametrize("cypher", ["CREATE (:Port {name: 'x'})", "MATCH (p:Port) SET p.name = 'x'",
                                    "MATCH (p:Port) DETACH DELETE p"])
def test_writes_are_refused_before_running(conn, cypher):
    with pytest.raises(lookup.LookupError, match="modify"):
        lookup.check(conn, cypher)


def test_syntax_errors_are_caught(conn):
    with pytest.raises(lookup.LookupError, match="invalid Cypher"):
        lookup.check(conn, "MATCH (p:Port RETURN p")


def test_schema_lists_small_value_sets_and_hides_embeddings(conn):
    text = lookup.schema_text(conn)
    assert "tier: 'key'|'standard'|'strategic'" in text and "embedding" not in text
    assert "(:Shipment)-[:FOR]->(:Customer)" in text
