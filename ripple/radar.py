"""Risk radar: what today's news means for the network, before anyone asks.

Try it:  python -m ripple.radar

For every recent, serious news alert that MENTIONS a port in the graph:

  1. Duration: read from the alert ("72-hour strike" -> 3 days, "four days"
     -> 4), otherwise 3 days for a high-severity alert and 1 for a medium one.
  2. What is left of it: an alert from 29 November announcing a 3-day strike
     still has 1 day to run on "today" (1 December). Only that part is
     simulated; alerts that are already over are skipped.
  3. Impact: the same port-closure analysis as a question would run, all
     the ports an alert mentions combined (the typhoon hits Shanghai and
     Ningbo at once).

Alerts are then ranked by the value of cargo that would arrive later than
the customers tolerate, then by the number of late shipments.
"""

from datetime import date, timedelta

from . import queries
from .agent import parse_days
from .generate import SCENARIO_DATE

LOOKBACK_DAYS = 3
DEFAULT_DAYS = {"high": 3, "medium": 1}

RECENT_ALERTS = """
MATCH (a:Alert)-[:MENTIONS]->(p:Port)
WHERE a.severity IN ['high', 'medium'] AND a.date >= $since AND a.date <= $today
RETURN a.id AS id, a.text AS text, a.severity AS severity, a.date AS date,
       collect(p.code) AS port_codes, collect(p.name) AS port_names
ORDER BY date DESC, id
"""


def impact_row(conn, port_codes: list, port_names: list, days: int, start: date) -> dict:
    """What closing these ports for `days` from `start` does, all of them combined."""
    results = [queries.port_closure(conn, code, days, start) for code in port_codes]
    combined = queries.combine(results)  # each shipment once, with its largest delay
    return {
        "shipments": combined["shipments"], "customers": combined["customers"],
        "sla_breaches": combined["sla_breaches"], "ripple_customers": combined["downstream_customers"],
        "value_at_risk_usd": combined["value_at_risk_usd"],
        "value_beyond_tolerance_usd": combined["value_beyond_tolerance_usd"],
        # The question to ask Ripple for the full analysis.
        "question": f"{' and '.join('Port of ' + n for n in port_names)} closed for {days} day{'s' * (days != 1)}",
    }


def scan(conn, today: date = SCENARIO_DATE, lookback_days: int = LOOKBACK_DAYS) -> list[dict]:
    """One row per alert still in effect today, highest risk first."""
    rows = []
    alerts = conn.execute(RECENT_ALERTS, {"since": today - timedelta(days=lookback_days), "today": today})
    for alert in [dict(a) for a in alerts]:
        total_days = parse_days(alert["text"]) or DEFAULT_DAYS[alert["severity"]]
        remaining = total_days - (today - alert["date"]).days
        if remaining <= 0:
            continue  # already over
        rows.append({**alert, **impact_row(conn, alert["port_codes"], alert["port_names"], remaining, today),
                     "days_total": total_days, "days_remaining": remaining})
    rows.sort(key=lambda r: (-r["value_beyond_tolerance_usd"], -r["shipments"], r["id"]))
    return rows


if __name__ == "__main__":
    from . import db
    conn = db.connect()
    try:
        radar = scan(conn)
    finally:
        conn.close()
    print(f"\nRisk radar on {SCENARIO_DATE}: {len(radar)} alerts still in effect\n")
    for r in radar:
        print(f"  ${r['value_beyond_tolerance_usd']:>10,} beyond tolerance  {r['shipments']:>2} late  "
              f"{r['days_remaining']}d left  {', '.join(r['port_names'])}: {r['text'][:60]}")
