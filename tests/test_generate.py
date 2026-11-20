"""Checks on the synthetic dataset and on the committed Relate store."""

from ripple import db
from ripple.generate import SCENARIO_DATE, build_dataset


def test_dataset_sizes():
    data = build_dataset()
    assert len(data["ports"]) == 30
    assert len(data["vessels"]) == 40
    assert len(data["shipments"]) == 200
    assert len(data["customers"]) == 60


def test_dataset_is_deterministic():
    assert build_dataset() == build_dataset()


def test_shipments_are_consistent():
    for s in build_dataset()["shipments"]:
        assert s["departure"] < s["eta"]
        assert s["origin"] != s["destination"]
        assert (s["status"] == "delivered") == (s["eta"] < SCENARIO_DATE)


def test_store_has_a_multi_hop_path():
    """Port <- Route <- Vessel <- Shipment -> Customer exists in the store."""
    conn = db.connect()
    try:
        row = conn.execute(
            "MATCH (:Port {name: $port})<-[:CALLS_AT]-(:Route)<-[:SAILS]-(:Vessel)"
            "<-[:ON_VESSEL]-(s:Shipment)-[:FOR]->(c:Customer) "
            "RETURN count(DISTINCT s) AS shipments, count(DISTINCT c) AS customers",
            {"port": "Rotterdam"},
        ).fetchone()
    finally:
        conn.close()
    assert row["shipments"] > 0 and row["customers"] > 0


def test_ports_have_real_positions_with_their_source():
    from ripple.generate import PORT_NAMES, POSITIONS
    assert {c for c, *_ in PORT_NAMES} == set(POSITIONS)  # one open-data record per port
    conn = db.connect()
    try:
        rows = {r["code"]: dict(r) for r in conn.execute(
            "MATCH (p:Port) RETURN p.code AS code, p.lat AS lat, p.lon AS lon, p.position_source AS src")}
    finally:
        conn.close()
    assert rows["NLRTM"]["src"] == "Wikidata Q1027807"  # the port itself, not the city
    for code, row in POSITIONS.items():
        assert rows[code]["lat"] == float(row["latitude"]) and rows[code]["lon"] == float(row["longitude"])
