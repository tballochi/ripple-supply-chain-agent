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
# Geography: ports within a distance of a point, using the location property
# (a WGS-84 point) and Relate's point index.
PORTS_NEAR_POINT = """
MATCH (p:Port)
WITH p, point.distance(p.location, point({latitude: $lat, longitude: $lon})) / 1000 AS km
WHERE km <= $radius_km
RETURN p.code AS code, p.name AS name, round(km) AS km ORDER BY km
"""
NEAREST_PORT = """
MATCH (p:Port)
RETURN p.name AS name, round(point.distance(p.location, point({latitude: $lat, longitude: $lon})) / 1000) AS km
ORDER BY km LIMIT 1
"""
PORT_POSITION = "MATCH (p:Port {code: $code}) RETURN p.lat AS lat, p.lon AS lon"

# Sea areas and coasts a question may name: centre (latitude, longitude) and
# the radius that roughly covers them, in km. Real geography.
AREAS = {
    "gulf of mexico": (25.0, -90.0, 900),
    "caribbean": (15.0, -75.0, 1200),
    "us east coast": (36.0, -75.0, 900),
    "us west coast": (37.0, -122.0, 900),
    "south china sea": (12.0, 113.0, 1200),
    "east china sea": (30.0, 125.0, 600),
    "yellow sea": (35.5, 123.5, 500),
    "sea of japan": (40.0, 135.0, 700),
    "taiwan strait": (24.5, 119.5, 300),
    "strait of malacca": (3.0, 100.5, 500),
    "malacca strait": (3.0, 100.5, 500),
    "bay of bengal": (15.0, 88.0, 900),
    "arabian sea": (16.0, 65.0, 1000),
    "persian gulf": (26.5, 52.5, 600),
    "red sea": (20.0, 38.5, 900),
    "suez canal": (30.6, 32.3, 150),
    "mediterranean": (37.0, 15.0, 1600),
    "strait of gibraltar": (35.95, -5.6, 150),
    "english channel": (50.2, -1.0, 350),
    "north sea": (56.0, 3.0, 600),
    "baltic sea": (58.0, 20.0, 600),
}
RADIUS = re.compile(r"(\d[\d,]*)\s*(km|kilometers?|kilometres?|miles?)\b", re.IGNORECASE)

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


def parse_radius_km(text: str) -> int | None:
    """'within 500 km of ...' -> 500, '300 miles around ...' -> 483."""
    match = RADIUS.search(text)
    if not match:
        return None
    value = int(match.group(1).replace(",", ""))
    return round(value * 1.609) if match.group(2).lower().startswith("mile") else value


def ports_near(conn, lat: float, lon: float, radius_km: float) -> list[dict]:
    return [dict(r) for r in conn.execute(PORTS_NEAR_POINT, {"lat": lat, "lon": lon, "radius_km": radius_km})]


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

    radius = parse_radius_km(text)
    area = None
    if ports and radius:
        # "within 500 km of Singapore": every port in that circle.
        centre = ports[0]
        at = conn.execute(PORT_POSITION, {"code": centre["code"]}).fetchone()
        ports = [{"code": p["code"], "name": p["name"],
                  "matched_by": f"{p['km']:.0f} km from {centre['name']} (radius {radius} km)"}
                 for p in ports_near(conn, at["lat"], at["lon"], radius)]
    if not ports and not vessels:
        # A sea area or a coast ("hurricane in the Gulf of Mexico"), longest name first.
        for name in sorted(AREAS, key=len, reverse=True):
            if name in lowered:
                lat, lon, area_radius = AREAS[name]
                area_radius = radius or area_radius
                nearest = conn.execute(NEAREST_PORT, {"lat": lat, "lon": lon}).fetchone()
                display = " ".join(w if w == "of" else ("US" if w == "us" else w.capitalize())
                                   for w in name.split())
                area = {"name": display, "radius_km": area_radius,
                        "nearest_port": nearest["name"], "nearest_km": nearest["km"]}
                ports = [{"code": p["code"], "name": p["name"],
                          "matched_by": f"{p['km']:.0f} km from the {area['name']} centre"}
                         for p in ports_near(conn, lat, lon, area_radius)]
                break
    if not ports and not vessels and not area:
        # No port named: maybe a country or a region ("ports in China").
        ports = [dict(r) for r in conn.execute(PORTS_BY_PLACE, {"text": lowered})]
    if not ports and not vessels and not area and alerts and alerts[0]["confident"] and alerts[0]["ports"]:
        # Still nothing: follow MENTIONS from the best alert, if it is a clear match.
        best = alerts[0]
        ports = [{**p, "matched_by": f"alert {best['id']}", "alert": best["text"]} for p in best["ports"]]

    return {"text": text, "mode": found["mode"], "ports": ports, "vessels": vessels,
            "alerts": alerts, "area": area}


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
