"""MCP server: expose the Ripple graph as tools for any agent.

Run with:  python -m ripple.mcp_server      (stdio transport)

MCP (Model Context Protocol) is a standard way to give tools to an AI agent.
Once this server is registered in Claude Code, Cursor or any MCP client, the
agent can ask "what if Rotterdam closes for 3 days?" and call these tools
itself. Every answer carries the graph paths, so the calling agent can
explain its reasoning too.

The store is opened read-only: no tool can modify the graph.
"""

import json

import relate
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from . import agent, db, queries, retrieval

server = MCPServer(
    "ripple",
    instructions=(
        "Supply chain graph (synthetic data): ports, routes, vessels, shipments, products, "
        "customers and news alerts. The scenario's 'today' is 2026-12-01. Start with "
        "analyze_disruption for a free-text question. Use the *_impact tools when you already "
        "know the port or vessel. Each impacted shipment comes with `path`, the chain of "
        "relationships from the disruption to the customer: quote it when you explain."),
)

# Errors the caller can fix (unknown port, bad Cypher...) are raised as
# ToolError so the agent sees the message; other exceptions would only show
# "Error executing tool".

IMPACT_FIELDS = ("shipment", "customer", "tier", "priority", "delay_days", "eta", "new_eta",
                 "sla_breached", "score", "reason", "vessel", "route", "origin", "destination",
                 "value_usd", "products", "path")


def plain(value):
    """Make a result JSON-friendly (dates become text)."""
    return json.loads(json.dumps(value, default=str))


def compact(result: dict, limit: int) -> dict:
    """An impact result trimmed to what an agent needs."""
    return plain({
        "disruption": result["disruption"],
        "summary": result["summary"],
        "impacted_shipments": [{k: r[k] for k in IMPACT_FIELDS} for r in result["impacted"][:limit]],
        "second_order": [{k: r[k] for k in ("customer", "via_customer", "via_shipment", "delay_days", "path")}
                         for r in result["downstream"][:limit]],
        "alternative_ports": [{k: a[k] for k in ("name", "code", "country", "km", "shared_routes")}
                              for a in result["alternatives"][:5]],
    })


def find_port(conn, port: str) -> str:
    row = conn.execute(
        "MATCH (p:Port) WHERE toLower(p.name) = toLower($x) OR p.code = toUpper($x) RETURN p.code AS code",
        {"x": port.strip()}).fetchone()
    if row is None:
        names = [r["name"] for r in conn.execute("MATCH (p:Port) RETURN p.name AS name ORDER BY name")]
        raise ToolError(f"Unknown port '{port}'. Ports in the graph: {', '.join(names)}")
    return row["code"]


def find_vessel(conn, vessel: str) -> str:
    row = conn.execute(
        "MATCH (v:Vessel) WHERE toLower(v.name) = toLower($x) OR v.imo = toUpper($x) RETURN v.imo AS imo",
        {"x": vessel.strip()}).fetchone()
    if row is None:
        raise ToolError(f"Unknown vessel '{vessel}'. Find names with read_cypher: "
                         "MATCH (v:Vessel) RETURN v.name LIMIT 50")
    return row["imo"]


# A Relate connection belongs to the thread that opened it, and the MCP
# server may run tools on worker threads: each tool opens its own.

@server.tool()
def analyze_disruption(question: str, limit: int = 10) -> dict:
    """Answer a free-text disruption question, e.g. "Port of Rotterdam closed for 3 days"
    or "the ransomware attack in Korea". Resolves the text to ports or vessels (names,
    countries, or matching news alerts), runs the impact analysis, and returns the
    explanation, the impacted shipments ranked by score and the graph path of each."""
    conn = db.connect()
    try:
        out = agent.answer(conn, question, use_llm=False)
    finally:
        conn.close()
    return plain({
        "explanation": out["explanation"],
        "matched": {"ports": out["retrieval"]["ports"], "vessels": out["retrieval"]["vessels"]},
        "days": out["plan"]["days"], "days_assumed": out["plan"]["days_assumed"],
        "analyses": [compact(r, limit) for r in out["results"]],
    })


@server.tool()
def port_closure_impact(port: str, days: int = 3, limit: int = 10) -> dict:
    """Shipments and customers delayed if a port (name or code, e.g. "Rotterdam" or "NLRTM")
    is closed for `days` days from 2026-12-01. Walks Port <- Route <- Vessel <- Shipment ->
    Customer, plus customers supplied by late manufacturers, and lists alternative ports."""
    conn = db.connect()
    try:
        return compact(queries.port_closure(conn, find_port(conn, port), days), limit)
    finally:
        conn.close()


@server.tool()
def vessel_outage_impact(vessel: str, days: int = 3, limit: int = 10) -> dict:
    """Shipments and customers delayed if a vessel (name or IMO, e.g. "MV Silver Spirit")
    is out of service for `days` days."""
    conn = db.connect()
    try:
        return compact(queries.vessel_outage(conn, find_vessel(conn, vessel), days), limit)
    finally:
        conn.close()


@server.tool()
def compare_with_plain_rag(question: str, k: int = 10) -> dict:
    """Answer the same question two ways and compare: Ripple's graph walk versus plain RAG
    (top-k hybrid search over every record written as a text document, no relationships
    followed). Returns how many delayed shipments, affected customers and second-order
    customers each one finds, and the documents plain RAG retrieved."""
    conn = db.connect()
    try:
        out = agent.compare_with_plain_rag(conn, question, max(1, min(k, 50)))
    finally:
        conn.close()
    out["documents"] = [{"kind": d["kind"], "text": d["text"]} for d in out["documents"]]
    return plain(out)


@server.tool()
def search_alerts(text: str, limit: int = 5) -> dict:
    """Hybrid search (full-text + vector, fused by reciprocal rank) over the news alerts.
    Returns the best alerts with the ports each one mentions in the graph."""
    conn = db.connect()
    try:
        found = retrieval.search_alerts(conn, text, top=limit)
    finally:
        conn.close()
    fields = ("id", "text", "severity", "date", "rrf", "vector_rank", "fulltext_rank", "ports")
    return plain({"mode": found["mode"], "alerts": [{k: a[k] for k in fields} for a in found["alerts"]]})


@server.tool()
def get_schema() -> dict:
    """Node labels with their properties, and relationship types with their endpoints.
    Read this before writing a query for read_cypher."""
    conn = db.connect()
    try:
        nodes = {}
        for r in conn.execute("CALL db.schema.nodeTypeProperties()"):
            nodes.setdefault(r["nodeLabels"][0], {})[r["propertyName"]] = r["propertyTypes"][0]
        rels = [dict(r) for r in conn.execute(
            "MATCH (a)-[r]->(b) RETURN DISTINCT labels(a)[0] AS start, type(r) AS type, labels(b)[0] AS end "
            "ORDER BY start, type")]
    finally:
        conn.close()
    nodes.get("Alert", {}).pop("embedding", None)  # a 384-number vector, of no use to read
    return {"nodes": nodes,
            "relationships": [f"(:{r['start']})-[:{r['type']}]->(:{r['end']})" for r in rels]}


@server.tool()
def read_cypher(query: str, limit: int = 50) -> dict:
    """Run a read-only Cypher query on the graph and return up to `limit` rows.
    Writes are refused by the database. Do not return the Alert.embedding property."""
    conn = db.connect()
    try:
        cursor = conn.execute(query)
        rows = [row.data() for row in cursor.fetchmany(max(1, min(limit, 200)))]
        truncated = cursor.fetchone() is not None
    except relate.Error as error:  # syntax error, write on a read-only store...
        raise ToolError(f"Cypher error: {error}") from error
    finally:
        conn.close()
    return plain({"rows": rows, "truncated": truncated})


if __name__ == "__main__":
    server.run()  # stdio: the MCP client starts this process and talks over stdin/stdout
