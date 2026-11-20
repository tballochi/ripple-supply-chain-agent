"""Inside the graph: the data model as Relate reports it, and a read-only
Cypher console.

Everything here is read from the store at run time, not written by hand:
  - node labels with their properties (CALL db.schema.nodeTypeProperties())
  - relationship types between labels, with counts (one MATCH over all edges)
  - the indexes Relate maintains (SHOW INDEXES): vector, full-text, point, range

The console runs a query only after EXPLAIN has planned it as a pure read,
the same check as the LLM-written queries (ripple/lookup.py).
"""

import time

from . import lookup
from .viz import COLORS

NODE_PROPERTIES = "CALL db.schema.nodeTypeProperties()"
NODE_COUNTS = "MATCH (n) RETURN labels(n)[0] AS label, count(*) AS n ORDER BY label"
PATTERNS = """
MATCH (a)-[r]->(b)
RETURN labels(a)[0] AS source, type(r) AS rel, labels(b)[0] AS target, count(*) AS n
ORDER BY n DESC
"""
INDEXES = "SHOW INDEXES"

# Starting points for the console, each a question the graph answers in one query.
EXAMPLES = {
    "Which ports does Rotterdam's traffic depend on? (routes calling at both)": """
MATCH (p:Port {name: 'Rotterdam'})<-[:CALLS_AT]-(r:Route)-[:CALLS_AT]->(other:Port)
RETURN other.name AS port, count(DISTINCT r) AS shared_routes
ORDER BY shared_routes DESC, port LIMIT 10""",
    "Supply chains two tiers deep (variable-length SUPPLIES path)": """
MATCH p = (m:Customer)-[:SUPPLIES*2..3]->(end:Customer)
RETURN [n IN nodes(p) | n.name] AS chain, length(p) AS tiers LIMIT 10""",
    "Ports within 1,000 km of Singapore (point index)": """
MATCH (s:Port {name: 'Singapore'}), (p:Port)
WITH p, round(point.distance(s.location, p.location) / 1000) AS km
WHERE km <= 1000
RETURN p.name AS port, km ORDER BY km""",
    "Customers with the most cargo at sea, by value": """
MATCH (s:Shipment)-[:FOR]->(c:Customer)
WHERE s.status <> 'delivered'
RETURN c.name AS customer, c.tier AS tier, count(s) AS shipments, sum(s.value_usd) AS value_usd
ORDER BY value_usd DESC LIMIT 10""",
    "News alerts about strikes, and the ports they name (full-text index)": """
MATCH (a:Alert)
SEARCH a IN (FULLTEXT INDEX alert_text FOR 'strike' LIMIT 8) SCORE AS score
MATCH (a)-[:MENTIONS]->(p:Port)
RETURN round(score * 100) / 100 AS score, p.name AS port, a.text AS alert ORDER BY score DESC""",
}


def overview(conn) -> dict:
    counts = {r["label"]: r["n"] for r in conn.execute(NODE_COUNTS)}
    properties = {}
    for r in conn.execute(NODE_PROPERTIES):
        properties.setdefault(r["nodeLabels"][0], []).append(
            f"{r['propertyName']}: {r['propertyTypes'][0].replace(' NOT NULL', '')}")
    indexes = [{"name": r["name"], "type": r["type"], "on": f"{(r['labelsOrTypes'] or [''])[0]}"
                f"({', '.join(r['properties'] or [])})"}
               for r in conn.execute(INDEXES) if r["type"] != "LOOKUP"]
    return {"labels": [{"label": label, "count": n, "properties": properties.get(label, [])}
                       for label, n in counts.items()],
            "patterns": [dict(r) for r in conn.execute(PATTERNS)],
            "indexes": indexes}


def schema_dot(model: dict) -> str:
    """The data model as a Graphviz drawing: one box per label, one arrow per relationship type."""
    lines = ['digraph schema {', 'rankdir=LR; bgcolor="transparent";',
             'node [shape=box, style="rounded,filled", fontname="Helvetica", fontcolor="white", '
             'color="#1F2A44", penwidth=1.5];',
             'edge [fontname="Helvetica", fontsize=10, color="#64748B", fontcolor="#94A3B8"];']
    colours = {"Port": COLORS.get("Port"), "Route": COLORS.get("Route"), "Vessel": COLORS.get("Vessel"),
               "Shipment": COLORS.get("Shipment"), "Customer": COLORS.get("Customer")}
    for item in model["labels"]:
        fill = colours.get(item["label"]) or "#334155"
        lines.append(f'"{item["label"]}" [label="{item["label"]}\\n{item["count"]}", fillcolor="{fill}"];')
    for p in model["patterns"]:
        lines.append(f'"{p["source"]}" -> "{p["target"]}" [label="{p["rel"]} ({p["n"]})"];')
    return "\n".join(lines + ["}"])


def run(conn, cypher: str) -> dict:
    """Check that the query only reads, then run it. Raises lookup.QueryRefused."""
    cypher = cypher.strip().rstrip(";")
    lookup.check(conn, cypher)
    started = time.perf_counter()
    result = lookup.run(conn, cypher)
    return {**result, "ms": round((time.perf_counter() - started) * 1000, 1)}
