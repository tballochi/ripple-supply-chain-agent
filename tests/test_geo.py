"""Map data: every late shipment and customer lands at a real place."""

import pytest

from ripple import db, generate, geo, queries, radar


@pytest.fixture
def conn():
    c = db.connect()
    yield c
    c.close()


def test_every_customer_country_has_a_position():
    assert set(generate.CUSTOMER_COUNTRIES) <= set(geo.COUNTRY_CENTRES)


def test_impact_map_of_a_port_closure(conn):
    result = queries.port_closure(conn, "NLRTM", 3)
    m = geo.impact_map(conn, result)
    assert m["closed"]["name"] == "Rotterdam" and len(m["ports"]) == 30
    assert len(m["shipments"]) == result["summary"]["shipments"]  # one arc per late shipment
    assert {s["beyond_tolerance"] for s in m["shipments"]} == {True, False}
    assert sum(c["shipments"] for c in m["countries"]) == len(m["shipments"])
    assert m["ripple"]  # companies hit through their suppliers
    for arc in m["shipments"] + m["deliveries"] + m["ripple"]:
        for lon, lat in (arc["from"], arc["to"]):
            assert -180 <= lon <= 180 and -90 <= lat <= 90


def test_impact_map_of_a_vessel_outage_has_no_closed_port(conn):
    imo = conn.execute("MATCH (v:Vessel {name: 'MV Silver Spirit'}) RETURN v.imo AS imo").fetchone()["imo"]
    result = queries.vessel_outage(conn, imo, 4)
    assert geo.impact_map(conn, result)["closed"] is None


def test_radar_map_places_each_alerted_port(conn):
    rows = radar.scan(conn)
    points = geo.radar_map(conn, rows)
    assert len(points) == sum(len(r["port_codes"]) for r in rows)
    assert points[0]["name"] == "Rotterdam"
