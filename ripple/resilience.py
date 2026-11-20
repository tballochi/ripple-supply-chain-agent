"""Network weak points: which ports would hurt most if they closed?

Try it:  python -m ripple.resilience

The radar reacts to today's news; this looks ahead. Two measures per port:

  1. Dependence (one Cypher query over the whole network): how many routes
     and vessels call there, and how many customers depend on it at all,
     directly or up to 3 supplier tiers away (`-[:SUPPLIES*0..3]->`), whatever
     the dates. The structure of the network, independent of the schedule.
  2. Exposure (the same 4-hop analysis as a question, for every port): what a
     closure of N days from the scenario's "today" would actually delay, with
     the cargo that would arrive later than customers tolerate.

A port many customers depend on but with little exposure right now is a
risk for later; one with high exposure is a risk today.
"""

import time
from datetime import date

from . import queries
from .generate import SCENARIO_DATE

DEPENDENCE = """
MATCH (p:Port)
RETURN p.code AS code, p.name AS name, p.country AS country, p.lat AS lat, p.lon AS lon,
  size(COLLECT { MATCH (p)<-[:CALLS_AT]-(r:Route) RETURN r.id }) AS routes,
  size(COLLECT { MATCH (p)<-[:CALLS_AT]-(:Route)<-[:SAILS]-(v:Vessel) RETURN DISTINCT v.imo }) AS vessels,
  size(COLLECT { MATCH (p)<-[:CALLS_AT]-(:Route)<-[:SAILS]-(:Vessel)<-[:ON_VESSEL]-(:Shipment)
                       -[:FOR]->(:Customer)-[:SUPPLIES*0..3]->(d:Customer)
                 RETURN DISTINCT d.id }) AS dependent_customers
ORDER BY code
"""


def rank_ports(conn, days: int = 3, start: date = SCENARIO_DATE) -> dict:
    """Every port with its dependence and its exposure to an N-day closure, worst first."""
    started = time.perf_counter()
    dependence = [dict(r) for r in conn.execute(DEPENDENCE)]
    dependence_ms = round((time.perf_counter() - started) * 1000, 1)
    ports, queries_run = [], 1
    for port in dependence:
        result = queries.port_closure(conn, port["code"], days, start)
        queries_run += len(result["trace"])
        impact = queries.combine([result])
        ports.append({**port, "shipments": impact["shipments"], "customers": impact["customers"],
                      "ripple_customers": impact["downstream_customers"], "sla_breaches": impact["sla_breaches"],
                      "value_at_risk_usd": impact["value_at_risk_usd"],
                      "value_beyond_tolerance_usd": impact["value_beyond_tolerance_usd"],
                      "question": f"Port of {port['name']} closed for {days} days"})
    ports.sort(key=lambda p: (-p["value_beyond_tolerance_usd"], -p["shipments"], -p["dependent_customers"]))
    return {"days": days, "start": start, "ports": ports, "dependence_cypher": DEPENDENCE.strip(),
            "dependence_ms": dependence_ms, "queries": queries_run,
            "ms": round((time.perf_counter() - started) * 1000, 1)}


if __name__ == "__main__":
    from . import db
    conn = db.connect()
    try:
        report = rank_ports(conn)
    finally:
        conn.close()
    print(f"\nWeak points: every port closed for {report['days']} days from {report['start']} "
          f"({report['queries']} Relate queries, {report['ms']} ms)\n")
    for p in report["ports"][:10]:
        print(f"  {p['name']:<18} ${p['value_beyond_tolerance_usd']:>10,} beyond tolerance  {p['shipments']:>2} late  "
              f"{p['dependent_customers']:>2} customers depend on it  {p['routes']} routes")
