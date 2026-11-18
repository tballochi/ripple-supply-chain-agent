"""Checks on the diversion simulator."""

import math

import pytest

from ripple import db, mitigation, queries


@pytest.fixture(scope="module")
def conn():
    connection = db.connect()
    yield connection
    connection.close()


@pytest.fixture(scope="module")
def rotterdam(conn):
    return queries.port_closure(conn, "NLRTM", 3)


@pytest.mark.parametrize("fallback", ["BEANR", "DEHAM", "FRLEH", "GBFXT"])
def test_diverting_never_makes_things_worse(conn, rotterdam, fallback):
    sim = mitigation.simulate_diversion(conn, "NLRTM", fallback, 3, rotterdam)
    for row in sim["shipments"]:
        assert 0 <= row["delay_after"] <= row["delay_before"]
    assert sim["after"]["sla_breaches"] <= sim["before"]["sla_breaches"]
    assert sim["before"]["shipments_late"] == len(rotterdam["impacted"])
    assert sim["value_protected_usd"] >= 0


def test_delays_follow_the_documented_model(conn, rotterdam):
    sim = mitigation.simulate_diversion(conn, "NLRTM", "BEANR", 3, rotterdam)
    km = sim["fallback"]["km"]
    routes_at_antwerp = {r["route"] for r in __import__("ripple.generate", fromlist=["x"]).build_dataset()["calls"]
                         if r["port"] == "BEANR"}
    by_id = {r["shipment"]: r for r in rotterdam["impacted"]}
    for row in sim["shipments"]:
        original = by_id[row["shipment"]]
        sea = 0 if original["route_id"] in routes_at_antwerp else math.ceil(km / 800) + 1
        road = math.ceil(km / 500) if "Rotterdam" in (original["origin"], original["destination"]) else 0
        assert row["delay_after"] == min(original["delay_days"], sea + road)


def test_rotterdam_has_a_useful_diversion(conn, rotterdam):
    best = mitigation.best_diversion(conn, rotterdam)
    assert best is not None and best["breaches_avoided"] > 0 and best["value_protected_usd"] > 0
    assert best["fallback"]["code"] in {a["code"] for a in rotterdam["alternatives"]}


def test_fallback_must_be_a_nearby_port(conn, rotterdam):
    with pytest.raises(ValueError):
        mitigation.simulate_diversion(conn, "NLRTM", "USLAX", 3, rotterdam)


def test_no_alternative_means_no_diversion(conn):
    los_angeles = queries.port_closure(conn, "USLAX", 3)
    assert los_angeles["alternatives"] == [] and mitigation.best_diversion(conn, los_angeles) is None
