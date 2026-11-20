"""Map data: where a disruption's ripple lands on the globe.

The app draws these with pydeck; this module only turns query results into
rows with coordinates, so it can be tested without a browser.

  ports      every port of the graph (real positions)
  closed     the disrupted port
  shipments  one arc per late shipment, from its origin port to its
             destination port: a closure in Rotterdam delays cargo that
             never sails near it, like Felixstowe to Bremerhaven
  customers  the customers waiting for that cargo, and the companies they
             supply (second order), placed at the centre of their country:
             the graph knows a customer's country, not its address
  fallback   the port the best diversion goes to
"""

from collections import Counter

# Approximate centre of each customer country (latitude, longitude).
COUNTRY_CENTRES = {
    "Germany": (51.2, 10.4), "France": (46.6, 2.4), "Netherlands": (52.2, 5.3),
    "United Kingdom": (53.5, -1.8), "Spain": (40.2, -3.6), "Italy": (42.8, 12.6),
    "United States": (39.8, -98.6), "Brazil": (-14.2, -51.9), "Japan": (36.2, 138.3),
    "Singapore": (1.35, 103.82), "India": (22.0, 79.0), "United Arab Emirates": (23.4, 53.8),
}

PORTS = "MATCH (p:Port) RETURN p.code AS code, p.name AS name, p.lat AS lat, p.lon AS lon ORDER BY code"
SHIPMENT_ENDS = """
MATCH (s:Shipment)-[:ORIGIN]->(o:Port), (s)-[:DESTINATION]->(d:Port), (s)-[:FOR]->(c:Customer)
WHERE s.id IN $ids
RETURN s.id AS id, o.code AS origin, d.code AS destination, c.id AS customer, c.country AS country
"""
COUNTRIES = "MATCH (c:Customer) WHERE c.id IN $ids RETURN c.id AS id, c.country AS country"


def ports(conn) -> list[dict]:
    return [dict(r) for r in conn.execute(PORTS)]


def impact_map(conn, result: dict) -> dict:
    """Rows for the map of one disruption (a queries.port_closure or vessel_outage result)."""
    where = {p["code"]: p for p in ports(conn)}
    late = {r["shipment"]: r for r in result["impacted"]}
    shipments, first_order = [], Counter()
    for end in conn.execute(SHIPMENT_ENDS, {"ids": list(late)}):
        row, o, d = late[end["id"]], where[end["origin"]], where[end["destination"]]
        shipments.append({
            "shipment": end["id"], "customer": row["customer"], "delay_days": row["delay_days"],
            "beyond_tolerance": row["sla_breached"], "value_usd": row["value_usd"],
            "from_name": o["name"], "to_name": d["name"],
            "from": [o["lon"], o["lat"]], "to": [d["lon"], d["lat"]],
        })
        first_order[(end["destination"], end["country"])] += 1
    # Cargo leaves the destination port for the customer's country.
    deliveries = [{"from": [where[port]["lon"], where[port]["lat"]], "to": _centre(country),
                   "country": country, "customers": n}
                  for (port, country), n in sorted(first_order.items()) if country in COUNTRY_CENTRES]
    # Second order: the late customer's country to the country of the company it supplies.
    supplier_country = {r["id"]: r["country"] for r in conn.execute(COUNTRIES, {"ids": [
        c for r in result["downstream"] for c in (r["customer_id"], _customer_id(result, r["via_customer"]))]})}
    ripple = []
    for r in result["downstream"]:
        a = supplier_country.get(_customer_id(result, r["via_customer"]))
        b = supplier_country.get(r["customer_id"])
        if a in COUNTRY_CENTRES and b in COUNTRY_CENTRES:
            ripple.append({"from": _centre(a), "to": _centre(b), "customer": r["customer"],
                           "via": r["via_customer"], "hops": r["supplier_hops"]})
    countries = Counter(d["country"] for d in deliveries for _ in range(d["customers"]))
    d = result["disruption"]
    closed = where.get(d.get("code")) if d["kind"] == "port_closure" else None
    best = result.get("best_diversion")
    fallback = where.get(best["fallback"]["code"]) if best and best.get("shipments_rescued") else None
    return {
        "ports": list(where.values()),
        "closed": closed, "fallback": fallback,
        "shipments": shipments, "deliveries": deliveries, "ripple": ripple,
        "countries": [{"country": c, "position": _centre(c), "shipments": n} for c, n in countries.items()],
    }


def radar_map(conn, rows: list[dict]) -> list[dict]:
    """One point per port of each radar row, sized by the cargo at risk."""
    where = {p["code"]: p for p in ports(conn)}
    points = []
    for r in rows:
        for code in r["port_codes"]:
            p = where[code]
            points.append({"name": p["name"], "position": [p["lon"], p["lat"]], "severity": r["severity"],
                           "value": r["value_beyond_tolerance_usd"], "shipments": r["shipments"],
                           "text": r["text"]})
    return points


def _centre(country: str) -> list[float]:
    lat, lon = COUNTRY_CENTRES[country]
    return [lon, lat]


def _customer_id(result: dict, name: str) -> str | None:
    """The id of a first-order customer, from its name in the impacted rows."""
    return next((r["customer_id"] for r in result["impacted"] if r["customer"] == name), None)
