"""Checks on the plain RAG baseline and on the comparison with the graph."""

import pytest

from ripple import agent, db, plain_rag


@pytest.fixture(scope="module")
def conn():
    connection = db.connect()
    yield connection
    connection.close()


def test_every_record_becomes_a_document(conn):
    kinds = {}
    for d in plain_rag.build_documents(conn):
        kinds[d["kind"]] = kinds.get(d["kind"], 0) + 1
    assert kinds == {"shipment": 200, "vessel": 40, "route": 14, "customer": 60, "port": 30, "alert": 54}


def test_shipment_document_carries_its_one_hop_facts(conn):
    doc = next(d for d in plain_rag.build_documents(conn) if d["id"] == "S0001")
    for word in ("vessel", "route", "customer", "ETA"):
        assert word in doc["text"]


def test_search_returns_k_documents(conn):
    found = plain_rag.search(conn, "Port of Rotterdam closed for 3 days", k=7)
    assert len(found["documents"]) == 7


def test_counts_are_consistent(conn):
    out = agent.compare_with_plain_rag(conn, "Port of Rotterdam closed for 3 days")
    g, r = out["graph"], out["plain_rag"]
    assert r["shipments_found"] + len(out["missed_shipments"]) == g["shipments"]
    assert r["shipments_wrong"] == len(out["wrong_shipments"])
    assert r["shipments_found"] <= min(g["shipments"], out["k"])
    assert r["paths"] == 0 and g["paths"] == g["shipments"]


def test_graph_finds_far_more_for_a_multi_hop_question(conn):
    out = agent.compare_with_plain_rag(conn, "Port of Rotterdam closed for 3 days")
    assert out["graph"]["shipments"] >= 3 * max(1, out["plain_rag"]["shipments_found"])
    assert out["graph"]["second_order_customers"] > out["plain_rag"]["second_order_found"]


def test_baseline_is_not_a_strawman_on_a_one_hop_question(conn):
    # A vessel's shipments are one hop away: plain RAG should find some.
    out = agent.compare_with_plain_rag(conn, "MV Silver Spirit is out of service for 4 days")
    assert out["plain_rag"]["shipments_found"] > 0
