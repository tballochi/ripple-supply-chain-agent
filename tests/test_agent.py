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


def test_explanation_splits_on_board_and_not_loaded(conn):
    out = agent.answer(conn, "Port of Rotterdam closed for 3 days", use_llm=False)
    impacted = out["results"][0]["impacted"]
    on_board = sum(r["reason"].startswith("on board") for r in impacted)
    assert 0 < on_board < len(impacted)
    assert f"{on_board} are already on board" in out["explanation"]
    assert f"{len(impacted) - on_board} are not loaded yet" in out["explanation"]


def test_second_order_example_is_not_a_directly_hit_customer(conn):
    out = agent.answer(conn, "Port of Rotterdam closed for 3 days", use_llm=False)
    result = out["results"][0]
    direct = {r["customer"] for r in result["impacted"]}
    line = next(l for l in out["explanation"].split("\n") if l.startswith("Ripple effect"))
    example_customer = line.split("-[SUPPLIES]-> ")[-1].split("`")[0]
    assert example_customer not in direct


def test_explanation_names_the_best_diversion(conn):
    out = agent.answer(conn, "Port of Rotterdam closed for 3 days", use_llm=False)
    best = out["results"][0]["best_diversion"]
    assert best and f"divert to {best['fallback']['name']}" in out["explanation"]
    assert f"avoids {best['breaches_avoided']} of" in out["explanation"]


def test_explanation_is_honest_when_a_diversion_avoids_no_breach(conn):
    out = agent.answer(conn, "A ship is stuck at the entrance of the Suez canal for a week", use_llm=False)
    best = out["results"][0]["best_diversion"]
    assert best and best["breaches_avoided"] == 0
    assert "avoids none of the" in out["explanation"] and "protects" not in out["explanation"]


def test_llm_facts_list_only_true_second_order_customers(conn):
    out = agent.answer(conn, "Port of Rotterdam closed for 3 days", use_llm=False)
    facts = agent.facts_for_llm(out["results"], out["plan"])["analyses"][0]
    direct = {r["customer"] for r in out["results"][0]["impacted"]}
    names = [r["customer"] for r in facts["second_order_customers"]]
    assert names and len(names) == len(set(names)) and not set(names) & direct


def test_rate_limit_fallback_is_explained(conn, monkeypatch):
    def limited(*args, **kwargs):
        raise llm.LLMError("rate limit of the free tier reached, try again in a minute")
    monkeypatch.setattr(llm, "available", lambda: True)
    monkeypatch.setattr(llm, "chat_json", limited)
    monkeypatch.setattr(llm, "chat", limited)
    out = agent.answer(conn, "Port of Rotterdam closed for 3 days")
    assert out["explained_by"] == "rules"
    assert any("rate limit" in step for step in out["steps"])


def test_area_without_ports_gets_an_honest_answer(conn):
    out = agent.answer(conn, "hurricane in the Gulf of Mexico", use_llm=False)
    assert out["results"] == []
    assert "Gulf of Mexico" in out["explanation"] and "Savannah" in out["explanation"]
