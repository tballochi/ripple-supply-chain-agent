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
    assert metrics["Customers via suppliers"] == str(expected["downstream_customers"])


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


def test_mitigation_tab_shows_before_and_after():
    page = render("Port of Rotterdam closed for 3 days")
    assert "Mitigation" in {t.label for t in page.tabs}
    assert any(m.label == "Value protected" for m in page.metric)
    page.selectbox(key="fallback-0").set_value("BEANR").run()
    assert not page.exception


def test_keys_from_streamlit_secrets_reach_the_environment(monkeypatch, tmp_path):
    secrets = tmp_path / ".streamlit" / "secrets.toml"
    secrets.parent.mkdir()
    secrets.write_text('GROQ_API_KEY = "test-key-from-secrets"\n')
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)  # Streamlit reads .streamlit/secrets.toml from here
    page = AppTest.from_file(APP, default_timeout=60)
    page.run()
    assert not page.exception
    import os
    assert os.environ.get("GROQ_API_KEY") == "test-key-from-secrets"


def test_interactions_do_not_rerun_the_agent(monkeypatch):
    from ripple import agent
    calls = []
    real_answer = agent.answer
    monkeypatch.setattr(agent, "answer", lambda *a, **k: calls.append(1) or real_answer(*a, **k))
    page = AppTest.from_file(APP, default_timeout=60)
    page.session_state["question"] = "Port of Antwerp closed for 3 days"
    page.run()
    page.selectbox(key="fallback-0").set_value(page.selectbox(key="fallback-0").options[-1]).run()
    page.select_slider[0].set_value(20).run()
    assert not page.exception and len(calls) == 1


def test_several_ports_show_a_combined_impact():
    page = render("ports in China closed for 4 days")
    labels = {m.label for m in page.metric}
    assert {"Unique shipments late", "Hit twice, counted once"} <= labels


def test_scenario_builder_writes_and_runs_a_question():
    page = render()
    page.selectbox[0].set_value("Antwerp")
    page.slider[0].set_value(4)
    next(b for b in page.button if b.label == "Run scenario").click().run()
    assert page.session_state["question"] == "Port of Antwerp closed for 4 days from 2026-12-01"
    assert not page.exception and page.metric


def test_follow_up_in_the_ui():
    page = render("Port of Rotterdam closed for 3 days")
    page.text_input(key="question").set_value("and if it lasts a week?").run()
    assert not page.exception
    assert any("Follow-up of" in c.value for c in page.caption)
    assert page.subheader[0].value == "Rotterdam closed for 7 days"



def test_landing_page_shows_the_radar_and_analyze_runs_it():
    page = render()
    assert any(s.value.startswith("Risk radar") for s in page.subheader)
    page.button(key="radar-Scenario news-0").click().run()
    assert not page.exception
    assert page.session_state["question"].startswith("Port of Rotterdam")
    assert page.metric


def test_save_a_plan_and_find_it_in_the_decision_log():
    page = render("Port of Rotterdam closed for 3 days")
    page.button(key="save-0").click().run()
    assert not page.exception and any("Saved P-" in s.value for s in page.success)
    page.session_state["question"] = ""
    page.run()
    assert any(s.value == "Decision log" for s in page.subheader)


def test_live_radar_shows_real_headlines_without_the_network(monkeypatch):
    from datetime import UTC, datetime

    from ripple import live
    today = datetime.now(UTC).date()
    alert = {"id": "news-test", "source": "Example Wire", "kind": "news", "severity": "high", "date": today,
             "text": "Dockers walk out at Rotterdam, terminals closed", "url": "https://example.org/a",
             "days": 3, "ports": ["NLRTM"]}
    monkeypatch.setattr(live, "fetch", lambda conn, day=None: ([alert], ["GDACS: ConnectionError"]))
    page = AppTest.from_file(APP, default_timeout=60)
    page.session_state["radar_mode"] = "Live news"
    page.run()
    assert not page.exception
    assert any(s.value.startswith("Live risk radar") for s in page.subheader)
    assert any("Dockers walk out at Rotterdam" in m.value for m in page.markdown)
    assert any("Skipped: GDACS" in c.value for c in page.caption)
    page.button(key="radar-Live news-0").click().run()
    assert page.session_state["question"] == "Port of Rotterdam closed for 3 days"
