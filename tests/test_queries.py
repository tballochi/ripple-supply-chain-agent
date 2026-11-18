"""Checks on the impact queries, run against the committed store."""

from datetime import timedelta

import pytest

from ripple import db, queries
from ripple.generate import SCENARIO_DATE, build_dataset


@pytest.fixture(scope="module")
def conn():
    connection = db.connect()
    yield connection
    connection.close()


def expected_late_shipments(code: str, days: int) -> dict:
    """Recompute the impact in plain Python from the generator's output,
    without the graph, to cross-check the Cypher query."""
    data = build_dataset()
    reopen = SCENARIO_DATE + timedelta(days=days)
    call = {(c["route"], c["port"]): c for c in data["calls"]}
    late = {}
    for s in data["shipments"]:
        vessel = next(v for v in data["vessels"] if v["imo"] == s["vessel"])
        at_port = call.get((vessel["route"], code))
        if at_port is None or s["status"] == "delivered":
            continue
        arrival = vessel["voyage_start"] + timedelta(days=at_port["day"])
        still_ahead = call[(vessel["route"], s["destination"])]["seq"] >= at_port["seq"]
        if SCENARIO_DATE <= arrival < reopen and still_ahead:
            late[s["id"]] = (reopen - arrival).days
    return late


@pytest.mark.parametrize("code,days", [("NLRTM", 3), ("CNSHA", 5), ("EGPSD", 5), ("SGSIN", 2)])
def test_port_closure_matches_python_recomputation(conn, code, days):
    result = queries.port_closure(conn, code, days)
    found = {r["shipment"]: r["delay_days"] for r in result["impacted"]}
    assert found == expected_late_shipments(code, days)
    assert found, "this scenario is used in the demo and must not be empty"


def test_every_impact_carries_its_path(conn):
    result = queries.port_closure(conn, "NLRTM", 3)
    for r in result["impacted"]:
        labels = [n["label"] for n in r["path_nodes"]]
        assert labels == ["Port", "Route", "Vessel", "Shipment", "Customer"]
        assert r["path"].startswith("Rotterdam <-[CALLS_AT]- ")
        assert r["path"].endswith(f"-[FOR]-> {r['customer']}")
        assert 1 <= r["delay_days"] <= 3
        assert r["new_eta"] == r["eta"] + timedelta(days=r["delay_days"])


def test_impacts_are_ranked_by_score(conn):
    scores = [r["score"] for r in queries.port_closure(conn, "NLRTM", 3)["impacted"]]
    assert scores == sorted(scores, reverse=True)


def test_downstream_goes_through_a_late_manufacturer(conn):
    result = queries.port_closure(conn, "NLRTM", 3)
    assert result["downstream"]
    breached = {r["shipment"] for r in result["impacted"] if r["sla_breached"]}
    for r in result["downstream"]:
        assert r["via_shipment"] in breached
        assert "-[SUPPLIES]->" in r["path"]


def test_alternatives_exclude_the_closed_port(conn):
    alternatives = queries.port_closure(conn, "NLRTM", 3)["alternatives"]
    assert alternatives and all(a["code"] != "NLRTM" for a in alternatives)


def test_zero_day_closure_hits_nothing(conn):
    assert queries.port_closure(conn, "NLRTM", 0)["impacted"] == []


def test_vessel_outage(conn):
    imo = conn.execute(
        "MATCH (v:Vessel)<-[:ON_VESSEL]-(s:Shipment) WHERE s.status <> 'delivered' "
        "RETURN v.imo AS imo, count(*) AS n ORDER BY n DESC, imo LIMIT 1").fetchone()["imo"]
    result = queries.vessel_outage(conn, imo, 4)
    assert result["impacted"] and all(r["delay_days"] == 4 for r in result["impacted"])
    assert all(r["path_nodes"][0]["label"] == "Vessel" for r in result["impacted"])


def test_unknown_port_is_an_error(conn):
    with pytest.raises(ValueError):
        queries.port_closure(conn, "XXXXX", 3)


DEMO_PORTS = {"NLRTM": "Rotterdam", "CNSHA": "Shanghai", "EGPSD": "Port Said", "KRPUS": "Busan"}


def test_every_port_has_an_impact_for_a_three_day_closure(conn):
    """Any port a judge types must give a real answer, not an empty list."""
    codes = [r["code"] for r in conn.execute("MATCH (p:Port) RETURN p.code AS code ORDER BY code")]
    assert len(codes) == 30
    counts = {code: queries.port_closure(conn, code, 3)["summary"]["shipments"] for code in codes}
    too_small = {code: n for code, n in counts.items() if n < 3}
    assert not too_small, f"ports with fewer than 3 impacted shipments: {too_small}"
    for code, name in DEMO_PORTS.items():
        assert counts[code] >= 10, f"demo port {name} has only {counts[code]} impacted shipments"


def test_reason_tells_on_board_from_not_loaded_yet(conn):
    data = build_dataset()
    seq = {(c["route"], c["port"]): c["seq"] for c in data["calls"]}
    rows = queries.port_closure(conn, "NLRTM", 3)["impacted"]
    reasons = {r["reason"] for r in rows}
    assert reasons == {queries.ON_BOARD, queries.NOT_LOADED}  # Rotterdam shows both cases
    shipments = {s["id"]: s for s in data["shipments"]}
    for r in rows:
        loaded_before = seq[(r["route_id"], shipments[r["shipment"]]["origin"])] < seq[(r["route_id"], "NLRTM")]
        assert r["reason"] == (queries.ON_BOARD if loaded_before else queries.NOT_LOADED)


def test_second_order_count_excludes_directly_hit_customers(conn):
    result = queries.port_closure(conn, "NLRTM", 3)
    direct = {r["customer_id"] for r in result["impacted"]}
    only_downstream = {r["customer_id"] for r in result["downstream"]} - direct
    assert result["summary"]["downstream_customers"] == len(only_downstream) > 0
