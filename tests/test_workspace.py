"""Checks on the writable workspace: memory and decisions."""

import pytest

from ripple import agent, db, mitigation, workspace


@pytest.fixture
def ws(tmp_path, monkeypatch):
    monkeypatch.setenv("RIPPLE_WORKSPACE", str(tmp_path / "workspace.relate"))
    monkeypatch.setenv("RIPPLE_NO_EMBEDDINGS", "1")
    return tmp_path / "workspace.relate"


@pytest.fixture(scope="module")
def conn():
    connection = db.connect()
    yield connection
    connection.close()


def test_the_committed_store_is_never_written(ws, conn):
    before = (db.STORE_PATH / "graph.json").read_bytes()
    workspace.record_episode(agent.answer(conn, "Port of Rotterdam closed for 3 days", use_llm=False))
    assert (db.STORE_PATH / "graph.json").read_bytes() == before and ws.exists()


def test_episodes_are_recalled_by_port_newest_first(ws, conn):
    for days in (3, 7):
        workspace.record_episode(agent.answer(conn, f"Port of Rotterdam closed for {days} days", use_llm=False))
    workspace.record_episode(agent.answer(conn, "Typhoon near Shanghai", use_llm=False))
    rotterdam = workspace.recall(["NLRTM"], [])
    assert [r["days"] for r in rotterdam] == [7, 3] and rotterdam[0]["about"] == ["Rotterdam"]
    assert len(workspace.recall(["CNSHA"], [])) == 1


def test_a_plan_links_to_real_ports_and_shipments(ws, conn):
    out = agent.answer(conn, "Port of Rotterdam closed for 3 days", use_llm=False)
    sim = mitigation.simulate_diversion(conn, "NLRTM", "DEHAM", 3, out["results"][0])
    plan_id = workspace.save_plan(sim, out["question"])
    [plan] = workspace.list_plans()
    assert plan["id"] == plan_id and (plan["closed"], plan["fallback"]) == ("Rotterdam", "Hamburg")
    assert plan["shipments_rescued"] == sim["shipments_rescued"] and plan["customers_protected"]


def test_workspace_is_rebuilt_when_the_data_changes(ws, conn):
    workspace.record_episode(agent.answer(conn, "Port of Rotterdam closed for 3 days", use_llm=False))
    (ws.parent / (ws.name + ".base")).write_text("older data")
    assert workspace.recall(["NLRTM"], []) == []  # fresh copy, memory dropped


def test_agent_recalls_earlier_analyses_when_asked_to_remember(ws, conn):
    agent.answer(conn, "Port of Rotterdam closed for 3 days", use_llm=False, remember=True)
    out = agent.answer(conn, "Port of Rotterdam closed for 7 days", use_llm=False, remember=True)
    assert out["earlier"] and out["earlier"][0]["days"] == 3
    assert "Earlier analyses" in out["explanation"]
