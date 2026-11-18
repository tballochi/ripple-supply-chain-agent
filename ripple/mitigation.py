"""Mitigation simulator: divert vessels from a closed port to a fallback port.

Try it:  python -m ripple.mitigation Rotterdam Antwerp 3

The model is deliberately simple, so each number can be explained:

  - Instead of waiting outside the closed port P, each impacted vessel calls
    at the fallback port F, a port linked to P by NEAR in the graph.
  - Sea detour: none if F is already a call of the vessel's route (the graph
    tells us: (F)<-[:CALLS_AT]-(route)), otherwise the trip P -> F at
    800 km per day plus one day in port.
  - Cargo that had to be loaded or unloaded at P now moves between P and F
    by truck or short-sea feeder, at 500 km per day, but only up to 600 km
    (Rotterdam -> Hamburg yes, Busan -> Shanghai no). Beyond that it waits
    for P to reopen.
  - Cargo just passing through (loaded before P and going further, or loaded
    after P) only suffers the sea detour, if any.
  - A planner diverts a shipment only if that is faster than waiting for P to
    reopen: new delay = min(delay through F, delay waiting).

Everything else (which shipments, which customers, the original delays)
comes from the impact analysis in queries.py.
"""

import math
import sys

from . import queries

SEA_KM_PER_DAY = 800    # same speed as the generator's schedules
LAND_KM_PER_DAY = 500   # a truck or a short-sea feeder, door to door
MAX_TRANSFER_KM = 600   # beyond this, moving cargo between P and F is not an option
PORT_CALL_DAYS = 1      # an extra port call costs a day

FALLBACK = """
MATCH (p:Port {code: $code})-[near:NEAR]->(f:Port {code: $fallback})
RETURN f.name AS name, f.code AS code, near.km AS km,
       COLLECT { MATCH (f)<-[:CALLS_AT]-(r:Route) RETURN r.id } AS routes
"""


def _diverted(row: dict, port_name: str, km: int, fallback_routes: set) -> dict:
    """New delay and how the shipment travels when its vessel uses F."""
    on_route = row["route_id"] in fallback_routes
    sea_days = 0 if on_route else math.ceil(km / SEA_KM_PER_DAY) + PORT_CALL_DAYS
    by_road = port_name in (row["origin"], row["destination"])
    road_days = math.ceil(km / LAND_KM_PER_DAY) if by_road else 0
    via_fallback = sea_days + road_days
    possible = not by_road or km <= MAX_TRANSFER_KM
    diverted = possible and via_fallback < row["delay_days"]
    new_delay = via_fallback if diverted else row["delay_days"]
    if not possible:
        how = f"keeps waiting (its cargo is handled at the closed port, {km} km is too far to transfer)"
    elif not diverted:
        how = "keeps waiting (diverting is not faster)"
    else:
        how = ("vessel already calls there" if on_route else f"sea detour +{sea_days}d") + (
            f", transfer {km} km +{road_days}d" if by_road else "")
    return {
        "shipment": row["shipment"], "customer": row["customer"], "customer_id": row["customer_id"],
        "value_usd": row["value_usd"], "sla_days": row["sla_days"],
        "delay_before": row["delay_days"], "delay_after": new_delay, "diverted": diverted,
        "breach_before": row["sla_breached"], "breach_after": new_delay > row["sla_days"],
        "road_km": km if diverted and by_road else 0, "vessel": row["vessel"],
        "sea_detour": diverted and not on_route, "how": how,
    }


def _metrics(rows: list, key: str) -> dict:
    late = [r for r in rows if r[f"delay_{key}"] > 0]
    breached = [r for r in rows if r[f"breach_{key}"]]
    return {
        "shipments_late": len(late),
        "delay_days": sum(r[f"delay_{key}"] for r in rows),
        "sla_breaches": len(breached),
        "value_beyond_tolerance_usd": sum(r["value_usd"] for r in breached),
    }


def simulate_diversion(conn, code: str, fallback: str, days: int, impact: dict | None = None) -> dict:
    """Before/after metrics when port `code`, closed for `days` days, is
    replaced by the nearby port `fallback`. Pass `impact` (the result of
    queries.port_closure) to avoid running the impact query twice."""
    impact = impact or queries.port_closure(conn, code, days)
    target = conn.execute(FALLBACK, {"code": code, "fallback": fallback}).fetchone()
    if target is None:
        raise ValueError(f"{fallback} is not a nearby (NEAR) port of {code} in the graph")
    rows = [_diverted(r, impact["disruption"]["name"], target["km"], set(target["routes"]))
            for r in impact["impacted"]]
    before, after = _metrics(rows, "before"), _metrics(rows, "after")
    detour_vessels = {r["vessel"] for r in rows if r["sea_detour"]}
    return {
        "closed": impact["disruption"],
        "fallback": {"name": target["name"], "code": target["code"], "km": target["km"]},
        "before": before, "after": after,
        "shipments_rescued": sum(r["delay_after"] < r["delay_before"] for r in rows),
        "breaches_avoided": before["sla_breaches"] - after["sla_breaches"],
        "value_protected_usd": before["value_beyond_tolerance_usd"] - after["value_beyond_tolerance_usd"],
        # Extra distance: a P -> F -> back detour per vessel that is not on a
        # route calling at F, plus the transfers of cargo between P and F.
        "extra_sea_km": 2 * target["km"] * len(detour_vessels),
        "extra_road_km": sum(r["road_km"] for r in rows),
        "shipments": sorted(rows, key=lambda r: (r["delay_after"] - r["delay_before"], r["shipment"])),
    }


def best_diversion(conn, impact: dict) -> dict | None:
    """The fallback that avoids the most SLA breaches (then protects the most
    value). None if no fallback port helps at all."""
    d = impact["disruption"]
    options = [simulate_diversion(conn, d["code"], a["code"], d["days"], impact)
               for a in impact["alternatives"]]
    options = [o for o in options if o["shipments_rescued"] > 0]
    if not options:
        return None
    return max(options, key=lambda o: (o["breaches_avoided"], o["value_protected_usd"],
                                       -o["fallback"]["km"]))


if __name__ == "__main__":
    from . import db
    closed, fallback_name = (sys.argv[1:3] + ["Rotterdam", "Antwerp"][len(sys.argv[1:3]):])
    days = int(sys.argv[3]) if len(sys.argv) > 3 else 3
    conn = db.connect()
    try:
        names = {r["name"].lower(): r["code"] for r in conn.execute("MATCH (p:Port) RETURN p.name AS name, p.code AS code")}
        sim = simulate_diversion(conn, names[closed.lower()], names[fallback_name.lower()], days)
    finally:
        conn.close()
    b, a = sim["before"], sim["after"]
    print(f"\n{sim['closed']['name']} closed {days} days, divert to {sim['fallback']['name']} "
          f"({sim['fallback']['km']} km)\n")
    print(f"{'':30}{'before':>10}{'after':>10}")
    for label, key in [("Shipments late", "shipments_late"), ("Total delay (days)", "delay_days"),
                       ("Beyond tolerance", "sla_breaches"), ("Value beyond tolerance", "value_beyond_tolerance_usd")]:
        print(f"{label:30}{b[key]:>10,}{a[key]:>10,}")
    print(f"\n{sim['shipments_rescued']} shipments rescued, {sim['breaches_avoided']} breaches avoided, "
          f"${sim['value_protected_usd']:,} protected, +{sim['extra_sea_km']:,} km at sea, "
          f"+{sim['extra_road_km']:,} km by road or feeder")
    for r in sim["shipments"][:8]:
        print(f"  {r['shipment']} {r['customer']:<22} {r['delay_before']}d -> {r['delay_after']}d  {r['how']}")
