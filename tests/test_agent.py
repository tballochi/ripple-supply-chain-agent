"""Checks on the agent. The LLM is replaced by fakes: no key, no network."""

import pytest

from ripple import agent, db, llm


@pytest.fixture(scope="module")
def conn():
    connection = db.connect()
    yield connection
    connection.close()


@pytest.fixture(autouse=True)
def fulltext_only(monkeypatch):
    monkeypatch.setenv("RIPPLE_NO_EMBEDDINGS", "1")  # keep these tests fast


def fake_llm(monkeypatch, plan=None, explanation="", fail=False):
    """Make the agent believe a key is set and control what the LLM returns."""
    def chat_json(system, user):
        if fail:
            raise RuntimeError("network down")
        return plan

    def chat(system, user, as_json=False):
        if fail:
            raise RuntimeError("network down")
        return explanation

    monkeypatch.setattr(llm, "available", lambda: True)
    monkeypatch.setattr(llm, "chat_json", chat_json)
    monkeypatch.setattr(llm, "chat", chat)


@pytest.mark.parametrize("text,days", [
    ("closed for 3 days", 3), ("out for a week", 7), ("a 48-hour strike", 2),
    ("two days", 2), ("for 2 weeks", 14), ("closed", None), ("12 hours", 1),
])
def test_parse_days(text, days):
    assert agent.parse_days(text) == days


def test_rules_mode_end_to_end(conn):
    out = agent.answer(conn, "Port of Rotterdam closed for 3 days", use_llm=False)
    assert out["planned_by"] == out["explained_by"] == "rules"
    assert out["plan"]["ports"] == ["NLRTM"] and out["plan"]["days"] == 3
    top = out["results"][0]["impacted"][0]
    assert top["shipment"] in out["explanation"] and top["path"] in out["explanation"]


def test_rules_mode_says_when_duration_is_assumed(conn):
    out = agent.answer(conn, "the ransomware attack in Korea", use_llm=False)
    assert out["plan"]["ports"] == ["KRPUS"] and out["plan"]["days_assumed"]
    assert "assumed" in out["explanation"]


def test_unrelated_question_runs_no_query(conn):
    out = agent.answer(conn, "who won the world cup", use_llm=False)
    assert out["results"] == [] and "could not link" in out["explanation"]


def test_llm_mode_uses_the_llm_plan_and_text(conn, monkeypatch):
    fake_llm(monkeypatch, plan={"port_codes": ["NLRTM"], "vessel_imos": [], "days": 5,
                                "reasoning": "The Dutch port is Rotterdam."},
             explanation="Rotterdam is closed; many shipments are late.")
    out = agent.answer(conn, "the big Dutch port is shut for 5 days")
    assert out["planned_by"] == out["explained_by"] == "llm"
    assert out["results"][0]["disruption"]["days"] == 5
    assert out["explanation"].startswith("Rotterdam is closed")


def test_llm_plan_is_checked_against_the_graph(conn, monkeypatch):
    fake_llm(monkeypatch, plan={"port_codes": ["NLRTM", "ZZZZZ"], "vessel_imos": ["IMO000"], "days": 999},
             explanation="ok")
    out = agent.answer(conn, "Rotterdam closed")
    assert out["plan"]["ports"] == ["NLRTM"] and out["plan"]["vessels"] == []
    assert out["plan"]["days"] == agent.DEFAULT_DAYS and out["plan"]["days_assumed"]


def test_llm_explanation_with_invented_shipment_is_rejected(conn, monkeypatch):
    fake_llm(monkeypatch, plan={"port_codes": ["NLRTM"], "vessel_imos": [], "days": 3},
             explanation="Shipment S9999 is very late.")
    out = agent.answer(conn, "Rotterdam closed for 3 days")
    assert out["planned_by"] == "llm" and out["explained_by"] == "rules"
    assert "S9999" not in out["explanation"]


def test_llm_failure_falls_back_to_rules(conn, monkeypatch):
    fake_llm(monkeypatch, fail=True)
    out = agent.answer(conn, "Port of Rotterdam closed for 3 days")
    assert out["planned_by"] == out["explained_by"] == "rules"
    assert out["results"][0]["summary"]["shipments"] > 0
