"""Network weak points and the graph explorer."""

import pytest

from ripple import db, explore, lookup, queries, resilience


@pytest.fixture
def conn():
    c = db.connect()
    yield c
    c.close()


def test_every_port_is_ranked_worst_first(conn):
    report = resilience.rank_ports(conn, 3)
    ports = report["ports"]
    assert len(ports) == 30 and ports[0]["name"] == "Rotterdam"
    values = [p["value_beyond_tolerance_usd"] for p in ports]
    assert values == sorted(values, reverse=True)
    # The ranking uses the same analysis as a question.
    assert ports[0]["shipments"] == queries.port_closure(conn, "NLRTM", 3)["summary"]["shipments"]
    assert report["queries"] == 1 + 3 * 30


def test_dependence_counts_customers_through_suppliers(conn):
    rows = {r["code"]: dict(r) for r in conn.execute(resilience.DEPENDENCE)}
    direct = conn.execute("""
        MATCH (:Port {code: 'NLRTM'})<-[:CALLS_AT]-(:Route)<-[:SAILS]-(:Vessel)<-[:ON_VESSEL]-(:Shipment)
              -[:FOR]->(c:Customer) RETURN count(DISTINCT c) AS n""").fetchone()["n"]
    assert rows["NLRTM"]["dependent_customers"] > direct  # the suppliers' buyers count too
    assert rows["NLRTM"]["routes"] == 5


def test_graph_overview_is_read_from_relate(conn):
    model = explore.overview(conn)
    assert {i["label"]: i["count"] for i in model["labels"]}["Port"] == 30
    assert {"VECTOR", "FULLTEXT", "POINT"} <= {i["type"] for i in model["indexes"]}
    assert {"source": "Customer", "rel": "SUPPLIES", "target": "Customer", "n": 72} in model["patterns"]
    assert "digraph" in explore.schema_dot(model)


@pytest.mark.parametrize("name", list(explore.EXAMPLES))
def test_console_examples_return_rows(conn, name):
    assert explore.run(conn, explore.EXAMPLES[name])["rows"]


def test_console_refuses_writes(conn):
    with pytest.raises(lookup.QueryRefused):
        explore.run(conn, "CREATE (:Port {code: 'XXXXX'})")


def test_replay_command_inlines_parameters():
    command = queries.cli_command("MATCH (p:Port {code: $code}) WHERE p.lat > $lat RETURN p // note",
                                  {"code": "NLRTM", "lat": 50.5})
    assert command.endswith('"MATCH (p:Port {code: \'NLRTM\'}) WHERE p.lat > 50.5 RETURN p"')
