"""Graph queries: who is hit by a disruption, through which path, and what
the alternatives are.

Try it:  python -m ripple.queries Rotterdam 3

The model of a port closure is deliberately simple, so it can be explained:
  - The port is closed for N days starting on `start`.
  - A vessel scheduled to arrive during the closure waits outside until the
    port reopens. Its delay is (reopening date - scheduled arrival).
  - Every shipment that vessel still has to deliver at that port or at a
    later call of the route is late by the same number of days.

All the "who is affected" logic is in Cypher. Python only scores and formats
the rows that come back.
"""

import sys
from datetime import date, timedelta

from . import db
from .generate import SCENARIO_DATE

# Turns the matched path `p` into plain data: one entry per node, and for each
# relationship its type and direction. This is what lets the UI and the agent
# show the exact chain of hops instead of just the final answer.
PATH_COLUMNS = """
  [n IN nodes(p) | {label: labels(n)[0], name: coalesce(n.name, n.id)}] AS path_nodes,
  [i IN range(0, size(relationships(p)) - 1) |
     {type: type(relationships(p)[i]),
      forward: startNode(relationships(p)[i]) = nodes(p)[i]}] AS path_rels
"""

# Shipment and customer facts needed to score an impacted shipment.
SHIPMENT_COLUMNS = """
  s.id AS shipment, s.eta AS eta, s.status AS status, s.priority AS priority,
  s.value_usd AS value_usd, v.name AS vessel, r.id AS route_id, r.name AS route,
  orig.name AS origin, dest.name AS destination,
  cust.id AS customer_id, cust.name AS customer, cust.tier AS tier,
  cust.kind AS customer_kind, cust.sla_days AS sla_days,
  COLLECT { MATCH (s)-[:CONTAINS]->(pr:Product) RETURN pr.name ORDER BY pr.name } AS products
"""

# The 4-hop walk: closed port -> routes calling there -> vessels on those
# routes -> shipments on board -> customers waiting for them.
PORT_IMPACT = f"""
MATCH p = (port:Port {{code: $code}})<-[call:CALLS_AT]-(r:Route)<-[:SAILS]-(v:Vessel)
          <-[:ON_VESSEL]-(s:Shipment)-[:FOR]->(cust:Customer)
// When is this vessel scheduled to reach the closed port?
WITH p, port, call, r, v, s, cust, v.voyage_start + duration({{days: call.day}}) AS arrival
WHERE arrival >= $start AND arrival < $reopen AND s.status <> 'delivered'
// Keep only shipments unloaded at the closed port or later on the route.
MATCH (s)-[:DESTINATION]->(dest:Port)<-[dest_call:CALLS_AT]-(r)
WHERE dest_call.seq >= call.seq
MATCH (s)-[:ORIGIN]->(orig:Port)
RETURN {PATH_COLUMNS},
  duration.inDays(arrival, $reopen).days AS delay_days, arrival AS vessel_arrival,
  CASE WHEN dest = port THEN 'destination port is closed'
       WHEN orig = port THEN 'loading port is closed'
       ELSE 'vessel is held up at the closed port on its way' END AS reason,
  {SHIPMENT_COLUMNS}
"""

# A vessel out of service: a shorter walk, vessel -> shipments -> customers.
VESSEL_IMPACT = f"""
MATCH p = (v:Vessel {{imo: $imo}})<-[:ON_VESSEL]-(s:Shipment)-[:FOR]->(cust:Customer)
WHERE s.status <> 'delivered'
MATCH (v)-[:SAILS]->(r:Route)
MATCH (s)-[:DESTINATION]->(dest:Port)
MATCH (s)-[:ORIGIN]->(orig:Port)
RETURN {PATH_COLUMNS},
  $days AS delay_days, null AS vessel_arrival,
  'vessel is out of service' AS reason,
  {SHIPMENT_COLUMNS}
"""

# One more hop: buyers supplied by a manufacturer whose inputs are late.
DOWNSTREAM = f"""
UNWIND $late AS item
MATCH p = (s:Shipment {{id: item.shipment}})-[:FOR]->(maker:Customer)-[:SUPPLIES]->(buyer:Customer)
RETURN {PATH_COLUMNS},
  buyer.id AS customer_id, buyer.name AS customer, buyer.tier AS tier,
  maker.name AS via_customer, s.id AS via_shipment, item.delay_days AS delay_days
"""

# Nearby ports that could take the cargo instead. `shared_routes` lists the
# routes that already call at both ports: for those, no detour is needed.
ALTERNATIVES = """
MATCH (port:Port {code: $code})-[near:NEAR]->(alt:Port)
RETURN alt.code AS code, alt.name AS name, alt.country AS country, near.km AS km,
  COLLECT { MATCH (alt)<-[:CALLS_AT]-(r:Route)-[:CALLS_AT]->(port) RETURN r.id ORDER BY r.id } AS shared_routes
ORDER BY size(shared_routes) DESC, km
"""

PRIORITY_WEIGHT = {"standard": 1, "express": 2, "critical": 3}
TIER_WEIGHT = {"standard": 1.0, "key": 1.5, "strategic": 2.0}


def path_text(nodes: list, rels: list) -> str:
    """Render a path as 'Rotterdam <-[CALLS_AT]- Route <-[SAILS]- Vessel ...'."""
    out = nodes[0]["name"]
    for rel, node in zip(rels, nodes[1:]):
        arrow = f"-[{rel['type']}]->" if rel["forward"] else f"<-[{rel['type']}]-"
        out += f" {arrow} {node['name']}"
    return out


def score(row: dict) -> float:
    """Days late x shipment priority x customer tier, doubled when the delay
    exceeds what the customer tolerates (its SLA)."""
    breach = 2 if row["delay_days"] > row["sla_days"] else 1
    return row["delay_days"] * PRIORITY_WEIGHT[row["priority"]] * TIER_WEIGHT[row["tier"]] * breach


def _analyze(conn, impact_rows: list, alternatives: list, disruption: dict) -> dict:
    """Shared second half: score, rank, find downstream customers, summarize."""
    impacted = []
    for row in impact_rows:
        row = dict(row)
        row["new_eta"] = row["eta"] + timedelta(days=row["delay_days"])
        row["sla_breached"] = row["delay_days"] > row["sla_days"]
        row["score"] = score(row)
        row["path"] = path_text(row["path_nodes"], row["path_rels"])
        # Prefer an alternative port the vessel's own route already calls at.
        on_route = [a for a in alternatives if row["route_id"] in a["shared_routes"]]
        best = (on_route or alternatives or [None])[0]
        row["alternative"] = best and {**best, "on_same_route": bool(on_route)}
        impacted.append(row)
    # Highest score first; between equal scores, the most valuable cargo first.
    impacted.sort(key=lambda r: (-r["score"], -r["value_usd"], r["shipment"]))

    late_inputs = [{"shipment": r["shipment"], "delay_days": r["delay_days"]}
                   for r in impacted if r["customer_kind"] == "manufacturer" and r["sla_breached"]]
    downstream = []
    for row in conn.execute(DOWNSTREAM, {"late": late_inputs}):
        row = dict(row)
        row["path"] = path_text(row["path_nodes"], row["path_rels"])
        downstream.append(row)
    downstream.sort(key=lambda r: (-r["delay_days"], r["customer"], r["via_shipment"]))

    return {
        "disruption": disruption,
        "summary": {
            "shipments": len(impacted),
            "customers": len({r["customer_id"] for r in impacted}),
            "vessels": len({r["vessel"] for r in impacted}),
            "sla_breaches": sum(r["sla_breached"] for r in impacted),
            "value_at_risk_usd": sum(r["value_usd"] for r in impacted),
            "max_delay_days": max((r["delay_days"] for r in impacted), default=0),
            "downstream_customers": len({r["customer_id"] for r in downstream}),
        },
        "impacted": impacted,
        "downstream": downstream,
        "alternatives": alternatives,
    }


def port_closure(conn, code: str, days: int, start: date = SCENARIO_DATE) -> dict:
    """Impact of closing port `code` for `days` days from `start`."""
    port = conn.execute("MATCH (p:Port {code: $code}) RETURN p.name AS name", {"code": code}).fetchone()
    if port is None:
        raise ValueError(f"Unknown port code: {code}")
    reopen = start + timedelta(days=days)
    rows = conn.execute(PORT_IMPACT, {"code": code, "start": start, "reopen": reopen}).fetchall()
    alternatives = [dict(r) for r in conn.execute(ALTERNATIVES, {"code": code})]
    disruption = {"kind": "port_closure", "code": code, "name": port["name"],
                  "days": days, "start": start, "reopen": reopen}
    return _analyze(conn, rows, alternatives, disruption)


def vessel_outage(conn, imo: str, days: int, start: date = SCENARIO_DATE) -> dict:
    """Impact of vessel `imo` being out of service for `days` days."""
    vessel = conn.execute("MATCH (v:Vessel {imo: $imo}) RETURN v.name AS name", {"imo": imo}).fetchone()
    if vessel is None:
        raise ValueError(f"Unknown vessel: {imo}")
    rows = conn.execute(VESSEL_IMPACT, {"imo": imo, "days": days}).fetchall()
    disruption = {"kind": "vessel_outage", "code": imo, "name": vessel["name"],
                  "days": days, "start": start, "reopen": start + timedelta(days=days)}
    return _analyze(conn, rows, [], disruption)


def print_report(result: dict, top: int = 8) -> None:
    d, s = result["disruption"], result["summary"]
    print(f"\n{d['name']} unavailable for {d['days']} days ({d['start']} to {d['reopen']})")
    print(f"  {s['shipments']} shipments late on {s['vessels']} vessels, {s['customers']} customers, "
          f"{s['sla_breaches']} SLA breaches, ${s['value_at_risk_usd']:,} of cargo")
    print(f"\nTop {min(top, len(result['impacted']))} impacted shipments:")
    for r in result["impacted"][:top]:
        breach = "SLA BREACH" if r["sla_breached"] else "within SLA"
        print(f"  [{r['score']:>4.1f}] {r['shipment']} for {r['customer']} ({r['tier']}, {r['priority']}): "
              f"+{r['delay_days']}d, ETA {r['eta']} -> {r['new_eta']}, {breach}")
        print(f"         why:  {r['reason']}")
        print(f"         path: {r['path']}")
    if result["downstream"]:
        print(f"\nSecond-order impact ({s['downstream_customers']} customers supplied by a late manufacturer):")
        for r in result["downstream"][:top]:
            print(f"  {r['customer']}: +{r['delay_days']}d exposure\n         path: {r['path']}")
    if result["alternatives"]:
        print("\nAlternative ports:")
        for a in result["alternatives"][:4]:
            routes = ", ".join(a["shared_routes"]) or "none"
            print(f"  {a['name']} ({a['country']}), {a['km']} km away, routes already calling at both: {routes}")
    elif d["kind"] == "port_closure":
        print("\nNo alternative port within range in the graph.")


if __name__ == "__main__":
    name = sys.argv[1] if len(sys.argv) > 1 else "Rotterdam"
    days = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    conn = db.connect()
    try:
        # Exact name lookup only; fuzzy matching of free text comes in M3.
        port = conn.execute("MATCH (p:Port) WHERE toLower(p.name) = toLower($n) RETURN p.code AS code",
                            {"n": name}).fetchone()
        vessel = conn.execute("MATCH (v:Vessel) WHERE toLower(v.name) = toLower($n) RETURN v.imo AS imo",
                              {"n": name}).fetchone()
        if port:
            print_report(port_closure(conn, port["code"], days))
        elif vessel:
            print_report(vessel_outage(conn, vessel["imo"], days))
        else:
            sys.exit(f"No port or vessel named '{name}'.")
    finally:
        conn.close()
