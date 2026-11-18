"""Smoke test of the Streamlit page: it must render without an exception."""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from ripple import db, queries

APP = str(Path(__file__).resolve().parent.parent / "app.py")


@pytest.fixture(autouse=True)
def fulltext_only(monkeypatch):
    monkeypatch.setenv("RIPPLE_NO_EMBEDDINGS", "1")
    for key in ("GROQ_API_KEY", "MISTRAL_API_KEY"):  # never call a real LLM in tests
        monkeypatch.setenv(key, "")


def render(question=None):
    page = AppTest.from_file(APP, default_timeout=60)
    if question:
        page.session_state["question"] = question
    page.run()
    assert not page.exception
    return page


def test_empty_page_renders():
    assert render().metric == []


def test_port_closure_page_shows_the_impact():
    conn = db.connect()
    try:
        expected = queries.port_closure(conn, "NLRTM", 3)["summary"]
    finally:
        conn.close()
    page = render("Port of Rotterdam closed for 3 days")
    metrics = {m.label: m.value for m in page.metric}
    assert metrics["Shipments late"] == str(expected["shipments"])
    assert metrics["Second-order customers"] == str(expected["downstream_customers"])


@pytest.mark.parametrize("question", [
    "MV Silver Spirit is out of service for 4 days",   # vessel: no alternatives tab content
    "Port of Antwerp closed for 2 days",
    "Port of Los Angeles closed for 1 day",            # very few shipments, no slider
    "ports in China closed for 2 days",                # several ports at once
    "who won the world cup",                           # nothing matched
])
def test_other_pages_render(question):
    render(question)


def test_comparison_tab_renders():
    page = render("Port of Rotterdam closed for 3 days")
    assert {"Impact", "Graph vs plain RAG"} <= {t.label for t in page.tabs}
    assert any("Plain RAG" in str(df.value.columns.tolist()) for df in page.dataframe)
