"""Retrieval: connect a free-text disruption to nodes of the graph.

Try it:  python -m ripple.retrieval "the ransomware attack in Korea"

Two complementary steps:

1. Entity matching. Does the text name a port, a vessel, a country or a
   region that exists in the graph? ("Port of Rotterdam closed" -> Rotterdam)

2. Hybrid search over the news alerts. The text is compared to every alert
   in two ways, by shared words (full-text index, BM25) and by meaning
   (vector index). The two rankings are fused with Reciprocal Rank Fusion:
   an alert earns 1 / (60 + rank) from each list it appears in.
   The query then follows (Alert)-[:MENTIONS]->(Port), so a text that names
   no port at all ("the ransomware attack in Korea") still lands on one.

This is where plain vector search stops and the graph continues: retrieval
finds the alert, the MENTIONS relationship finds the port, and the impact
queries walk on from there.
"""

import re
import sys

from . import db, embeddings

# Words too common to help the word-based search. Relate's full-text index
# treats every word as a search term, so we remove these ourselves.
STOP_WORDS = set("""
a an and are as at be been being by can could did do does for from had has have how
if in into is it its of on or our that the their there these this those to was we
were what when where which who whom why will with would you your about after all any
due near next over than then until up us via
port ports day days week weeks closed close closure shipment shipments customer customers
affected impact impacted happens happen delay delayed late
container containers terminal terminals vessel vessels cargo
""".split())

# When is an alert found by meaning trusted to pick a port? It must be close
# enough (scores are cosine similarity mapped to 0..1, and unrelated texts
# already sit around 0.75) and it must stand out from the runner-up. A vague
# text such as "port closed" is equally close to many alerts: no clear winner.
MIN_SIMILARITY = 0.80
MIN_LEAD = 0.01

# Each branch returns (alert, which list, rank in that list, raw score).
VECTOR_BRANCH = """
  MATCH (a:Alert)
  SEARCH a IN (VECTOR INDEX alert_embedding FOR $vector LIMIT $k) SCORE AS score
  WITH a, score ORDER BY score DESC, a.id
  WITH collect({alert: a, score: score}) AS hits
  UNWIND range(0, size(hits) - 1) AS i
  RETURN hits[i].alert AS a, 'vector' AS source, i + 1 AS rank, hits[i].score AS score
"""
FULLTEXT_BRANCH = """
  MATCH (a:Alert)
  SEARCH a IN (FULLTEXT INDEX alert_text FOR $words LIMIT $k) SCORE AS score
  WITH a, score ORDER BY score DESC, a.id
  WITH collect({alert: a, score: score}) AS hits
  UNWIND range(0, size(hits) - 1) AS i
  RETURN hits[i].alert AS a, 'fulltext' AS source, i + 1 AS rank, hits[i].score AS score
"""
# Fuse the lists, keep the best alerts, then hop to the ports they mention.
FUSE = """
WITH a, sum(1.0 / (60 + rank)) AS rrf,
     min(CASE source WHEN 'vector' THEN rank END) AS vector_rank,
     min(CASE source WHEN 'fulltext' THEN rank END) AS fulltext_rank,
     max(CASE source WHEN 'vector' THEN score END) AS similarity
ORDER BY rrf DESC, a.id LIMIT $top
RETURN a.id AS id, a.text AS text, a.severity AS severity, a.date AS date,
       round(rrf, 4) AS rrf, vector_rank, fulltext_rank, similarity,
       COLLECT { MATCH (a)-[:MENTIONS]->(p:Port)
                 RETURN {code: p.code, name: p.name} ORDER BY p.name } AS ports
"""

# Entity matching is a substring test done by the database: does the text
# contain the name of a node?
PORTS_BY_NAME = """
MATCH (p:Port) WHERE $text CONTAINS toLower(p.name)
RETURN p.code AS code, p.name AS name, 'port name' AS matched_by ORDER BY name
"""
PORTS_BY_PLACE = """
MATCH (p:Port) WHERE $text CONTAINS toLower(p.country) OR $text CONTAINS toLower(p.region)
RETURN p.code AS code, p.name AS name,
       CASE WHEN $text CONTAINS toLower(p.country) THEN 'country: ' + p.country
            ELSE 'region: ' + p.region END AS matched_by ORDER BY name
"""
VESSELS_BY_NAME = """
MATCH (v:Vessel) WHERE $text CONTAINS toLower(v.name)
RETURN v.imo AS imo, v.name AS name ORDER BY name
"""


def keywords(text: str) -> list[str]:
    """Lower-case words of the text, without the stop words."""
    return [w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in STOP_WORDS]


def search_alerts(conn, text: str, top: int = 5, k: int = 20) -> dict:
    """Hybrid search over alerts. Returns the mode used and the ranked alerts."""
    words = keywords(text)
    vectors = embeddings.embed([text])
    branches, params = [], {"k": k, "top": top}
    if vectors:
        branches.append(VECTOR_BRANCH)
        params["vector"] = vectors[0]
    if words:
        branches.append(FULLTEXT_BRANCH)
        params["words"] = " ".join(words)
    if not branches:
        return {"mode": "none", "alerts": []}
    cypher = "CALL () {" + "UNION ALL".join(branches) + "}" + FUSE
    alerts = []
    for row in conn.execute(cypher, {**params, "top": 2 * k}):
        row = dict(row)
        # Meaningful words the question and the alert have in common.
        row["shared_words"] = sorted(set(words) & set(keywords(row["text"])))
        alerts.append(row)
    # How far ahead the closest alert by meaning is from the second closest.
    by_meaning = sorted((a["similarity"] for a in alerts if a["similarity"] is not None), reverse=True)
    lead = by_meaning[0] - by_meaning[1] if len(by_meaning) > 1 else 0.0
    for a in alerts:
        clear_by_meaning = a["vector_rank"] == 1 and a["similarity"] >= MIN_SIMILARITY and lead >= MIN_LEAD
        clear_by_words = a["fulltext_rank"] == 1 and len(a["shared_words"]) >= 2
        a["confident"] = clear_by_meaning or clear_by_words
    mode = "hybrid" if len(branches) == 2 else ("vector" if vectors else "fulltext")
    return {"mode": mode, "alerts": alerts[:top]}


def resolve(conn, text: str) -> dict:
    """Find what a disruption text refers to.

    Returns the ports and vessels it points at, how each was found, and the
    related alerts (shown to the user as supporting context).
    """
    lowered = text.lower()
    found = search_alerts(conn, text)
    alerts = found["alerts"]

    vessels = [dict(r) for r in conn.execute(VESSELS_BY_NAME, {"text": lowered})]
    ports = [dict(r) for r in conn.execute(PORTS_BY_NAME, {"text": lowered})]
    # "Port Said" contains "port": drop a name match that is only part of a
    # longer matched name (not needed today, but cheap insurance).
    ports = [p for p in ports
             if not any(p["name"] != q["name"] and p["name"].lower() in q["name"].lower() for q in ports)]

    if not ports and not vessels:
        # No port named: maybe a country or a region ("ports in China").
        ports = [dict(r) for r in conn.execute(PORTS_BY_PLACE, {"text": lowered})]
    if not ports and not vessels and alerts and alerts[0]["confident"] and alerts[0]["ports"]:
        # Still nothing: follow MENTIONS from the best alert, if it is a clear match.
        best = alerts[0]
        ports = [{**p, "matched_by": f"alert {best['id']}", "alert": best["text"]} for p in best["ports"]]

    return {"text": text, "mode": found["mode"], "ports": ports, "vessels": vessels, "alerts": alerts}


if __name__ == "__main__":
    question = " ".join(sys.argv[1:]) or "the ransomware attack in Korea"
    conn = db.connect()
    try:
        result = resolve(conn, question)
    finally:
        conn.close()
    print(f"\nQuestion: {question}\nSearch mode: {result['mode']}")
    for p in result["ports"]:
        print(f"  port   {p['name']} ({p['code']}), matched by {p['matched_by']}")
    for v in result["vessels"]:
        print(f"  vessel {v['name']} ({v['imo']}), matched by vessel name")
    if not result["ports"] and not result["vessels"]:
        print("  nothing in the graph matches this text")
    print("Related alerts (rrf = fused score, v/f = rank by meaning / by words):")
    for a in result["alerts"]:
        names = ", ".join(p["name"] for p in a["ports"]) or "no port"
        print(f"  {a['rrf']:.4f} v{a['vector_rank'] or '-'} f{a['fulltext_rank'] or '-'}  "
              f"{a['text'][:78]}  -> {names}")
