"""Free questions about the data, answered by LLM-written Cypher.

Try it (needs an LLM key):  python -m ripple.lookup "which customers buy sneakers?"

When a question is not about a disruption ("which customers buy sneakers?",
"how many vessels sail the Transatlantic route?"), the LLM writes one Cypher
query from the graph's schema. Three safety nets before any row comes back:

  1. EXPLAIN plans the query without running it: syntax errors and unknown
     functions are caught here, and the error is sent back to the LLM once
     so it can fix its query.
  2. EXPLAIN also reports the query type: anything that is not a pure read
     ('r') is refused.
  An empty result also gets one second chance: it is usually a relationship
  written in the wrong direction. At most two LLM calls per question.
  3. The store is opened read-only anyway, and at most 50 rows are read.
"""

import sys

import relate

from . import db, llm

MAX_ROWS = 50

CYPHER_SYSTEM = """You translate a question into ONE read-only Cypher query for a Relate graph
database (openCypher, Cypher 25). Rules:
- Use only the labels, properties and relationship directions of the schema below.
  Directions matter: (:Shipment)-[:FOR]->(:Customer) means a shipment is FOR a customer;
  writing (:Customer)-[:FOR]->(:Shipment) matches nothing.
- Read only: MATCH, OPTIONAL MATCH, WITH, WHERE, RETURN, ORDER BY, LIMIT, COLLECT { }, COUNT { }.
- No APOC, no GDS, no CREATE/MERGE/SET/DELETE, no CALL procedures.
- Return readable columns with aliases (names, not whole nodes). Never return Alert.embedding.
- Always end with LIMIT 50 or less.
- The scenario's "today" is 2026-12-01; dates are DATE values (compare with date('2026-12-05')).
Reply with JSON only: {"cypher": "<query>", "explanation": "<one short sentence>"}

Examples:
Q: which customers buy sneakers?
{"cypher": "MATCH (c:Customer)<-[:FOR]-(:Shipment)-[:CONTAINS]->(:Product {name: 'Sneakers'}) RETURN DISTINCT c.name AS customer, c.country AS country ORDER BY customer LIMIT 50", "explanation": "Customers with at least one shipment containing sneakers."}
Q: how many vessels sail each route?
{"cypher": "MATCH (v:Vessel)-[:SAILS]->(r:Route) RETURN r.name AS route, count(v) AS vessels ORDER BY vessels DESC LIMIT 50", "explanation": "Vessels counted per route."}

Schema:
"""


def schema_text(conn) -> str:
    """Labels with properties, and relationship patterns, as compact text.
    Text properties with few values list them, e.g. tier: 'key'|'standard'|'strategic',
    so the LLM filters on values that exist."""
    props = {}
    for r in conn.execute("CALL db.schema.nodeTypeProperties()"):
        label, name, kind = r["nodeLabels"][0], r["propertyName"], r["propertyTypes"][0]
        if name == "embedding":
            continue
        description = f"{name}: {kind}"
        if kind.startswith("STRING"):
            values = [v["v"] for v in conn.execute(
                f"MATCH (n:{label}) RETURN DISTINCT n.{name} AS v ORDER BY v LIMIT 13")]
            if len(values) <= 12:
                description = f"{name}: " + "|".join(repr(v) for v in values)
        props.setdefault(label, []).append(description)
    rels = [f"(:{r['a']})-[:{r['t']}]->(:{r['b']})" for r in conn.execute(
        "MATCH (a)-[r]->(b) RETURN DISTINCT labels(a)[0] AS a, type(r) AS t, labels(b)[0] AS b ORDER BY a, t")]
    nodes = [f"(:{label} {{{', '.join(sorted(p))}}})" for label, p in sorted(props.items())]
    return "\n".join(nodes + rels)


class QueryRefused(Exception):
    """The question could not be turned into a safe, valid query."""


def check(conn, cypher: str) -> None:
    """Plan the query without running it; refuse anything but a pure read."""
    try:
        query_type = conn.execute("EXPLAIN " + cypher).consume().query_type
    except relate.Error as error:
        raise QueryRefused(f"invalid Cypher: {str(error).splitlines()[0]}") from error
    if query_type != "r":
        raise QueryRefused("the query would modify the graph, refused")


def plain_value(value):
    """Rows as plain values for display (nodes become their name or id)."""
    if isinstance(value, relate.Node):
        return value.get("name") or value.get("id") or value.get("code") or str(value)
    if isinstance(value, list):
        return [plain_value(v) for v in value]
    return value


def ask(conn, question: str) -> dict:
    """Question -> Cypher (LLM) -> checked -> rows. Raises QueryRefused or llm.LLMError."""
    system = CYPHER_SYSTEM + schema_text(conn)
    answer = llm.chat_json(system, question)
    cypher = str(answer.get("cypher", "")).strip().rstrip(";")
    repaired = False
    try:
        check(conn, cypher)
    except QueryRefused as error:  # one repair round, with the error message
        answer, cypher, repaired = *repair(system, question, cypher, f"failed with: {error}"), True
        check(conn, cypher)
    result = run(conn, cypher)
    if not result["rows"] and not repaired:  # often a relationship in the wrong direction
        answer2, cypher2 = repair(system, question, cypher, "returned no rows. Check every relationship "
                                                            "direction against the schema.")
        try:
            check(conn, cypher2)
            second = run(conn, cypher2)
            if second["rows"]:
                answer, result = answer2, second
        except QueryRefused:
            pass
    return {**result, "explanation": str(answer.get("explanation", ""))[:300]}


def repair(system: str, question: str, cypher: str, problem: str) -> tuple[dict, str]:
    answer = llm.chat_json(system, f"{question}\n\nYour previous query:\n{cypher}\n{problem}\nFix it.")
    return answer, str(answer.get("cypher", "")).strip().rstrip(";")


def run(conn, cypher: str) -> dict:
    cursor = conn.execute(cypher)
    rows = [{k: plain_value(v) for k, v in row.items()} for row in cursor.fetchmany(MAX_ROWS)]
    return {"cypher": cypher, "columns": cursor.columns, "rows": rows,
            "truncated": cursor.fetchone() is not None}


def as_markdown(result: dict, limit: int = 10) -> str:
    """A small Markdown table of the first rows."""
    if not result["rows"]:
        return "_The query returned no rows._"
    columns = result["columns"]
    lines = ["| " + " | ".join(columns) + " |", "|" + "---|" * len(columns)]
    for row in result["rows"][:limit]:
        lines.append("| " + " | ".join(str(row[c]) for c in columns) + " |")
    more = len(result["rows"]) - limit
    if more > 0 or result["truncated"]:
        lines.append(f"\n_...and more rows ({len(result['rows'])}{'+' if result['truncated'] else ''} in total)._")
    return "\n".join(lines)


if __name__ == "__main__":
    question = " ".join(sys.argv[1:]) or "which customers buy sneakers?"
    if not llm.available():
        sys.exit("Free questions need an LLM key in .env (see .env.example).")
    conn = db.connect()
    try:
        out = ask(conn, question)
    finally:
        conn.close()
    print(f"\nQ: {question}\nCypher: {out['cypher']}\n\n{as_markdown(out)}")
