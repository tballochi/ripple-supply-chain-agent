"""Plain RAG baseline: what you get WITHOUT walking the graph.

Try it:  python -m ripple.plain_rag "Port of Rotterdam closed for 3 days"

To keep the comparison honest, the baseline gets the same data and the same
question as Ripple:

  - Every record of the graph becomes a text document, the way you would
    chunk a database for RAG: one document per shipment (with its vessel,
    route, origin, destination, customer, products and dates), per vessel,
    per route (with its ordered port calls), per customer (with the buyers
    it supplies), per port, and per news alert.
  - The question retrieves the top-k documents with the same hybrid search
    as Ripple (word match + meaning, fused by reciprocal rank).
  - We then count what those documents name: shipments and customers.

What it cannot do is follow relationships: from "Rotterdam" to the routes
calling there, to the vessels on those routes and their dates, to the
cargo on board, to the customers, and on to the buyers those customers
supply. compare() measures exactly that gap against Ripple's answer.
"""

import json
import math
import sys
from collections import Counter

from . import embeddings, retrieval

RRF_K = 60  # same fusion constant as the Cypher hybrid search

DOC_QUERIES = {
    "shipment": """
        MATCH (s:Shipment)-[:ON_VESSEL]->(v:Vessel)-[:SAILS]->(r:Route),
              (s)-[:FOR]->(c:Customer), (s)-[:ORIGIN]->(o:Port), (s)-[:DESTINATION]->(d:Port)
        RETURN s.id AS id, c.id AS customer_id,
          'Shipment ' + s.id + ' (' + s.priority + ' priority, ' + s.status + ', value $' +
          toString(s.value_usd) + ') carries ' +
          string.join(COLLECT { MATCH (s)-[:CONTAINS]->(p:Product) RETURN p.name ORDER BY p.name }, ', ') +
          ' for customer ' + c.name + ' (' + c.country + '). It sails on vessel ' + v.name +
          ' on route ' + r.name + ' from ' + o.name + ' to ' + d.name + ', departing ' +
          toString(s.departure) + ', ETA ' + toString(s.eta) + '.' AS text
        ORDER BY id""",
    "vessel": """
        MATCH (v:Vessel)-[:SAILS]->(r:Route)
        RETURN v.imo AS id, null AS customer_id,
          'Vessel ' + v.name + ' (' + v.imo + ', ' + toString(v.capacity_teu) + ' TEU) sails route ' +
          r.name + '. Its current voyage started on ' + toString(v.voyage_start) + '.' AS text
        ORDER BY id""",
    "route": """
        MATCH (r:Route)
        RETURN r.id AS id, null AS customer_id,
          'Route ' + r.id + ' ' + r.name + ' calls at ' +
          string.join(COLLECT { MATCH (r)-[c:CALLS_AT]->(p:Port)
                                RETURN p.name + ' (day ' + toString(c.day) + ')' ORDER BY c.seq }, ', ') +
          '. Vessels: ' + string.join(COLLECT { MATCH (v:Vessel)-[:SAILS]->(r) RETURN v.name ORDER BY v.name }, ', ') +
          '.' AS text
        ORDER BY id""",
    "customer": """
        MATCH (c:Customer)
        RETURN c.id AS id, c.id AS customer_id,
          'Customer ' + c.name + ' is a ' + c.tier + ' ' + c.kind + ' in ' + c.country +
          ' that tolerates ' + toString(c.sla_days) + ' day(s) of delay.' +
          CASE WHEN EXISTS { (c)-[:SUPPLIES]->() }
               THEN ' It supplies ' + string.join(COLLECT { MATCH (c)-[:SUPPLIES]->(b:Customer)
                                                            RETURN b.name ORDER BY b.name }, ', ') + '.'
               ELSE '' END AS text
        ORDER BY id""",
    "port": """
        MATCH (p:Port)
        RETURN p.code AS id, null AS customer_id,
          'Port of ' + p.name + ' (' + p.code + '), ' + p.country + ', ' + p.region + '.' AS text
        ORDER BY id""",
    "alert": """
        MATCH (a:Alert)
        RETURN a.id AS id, null AS customer_id,
          'News ' + toString(a.date) + ' (' + a.severity + '): ' + a.text AS text
        ORDER BY id""",
}

_index = None  # built once per process: documents, word statistics, vectors


def build_documents(conn) -> list[dict]:
    docs = []
    for kind, cypher in DOC_QUERIES.items():
        for row in conn.execute(cypher):
            docs.append({"kind": kind, "id": row["id"], "text": row["text"],
                         "customer_id": row["customer_id"],
                         "shipment": row["id"] if kind == "shipment" else None})
    return docs


def _vectors(texts: list[str]) -> list[list[float]] | None:
    """Document vectors from the generator's cache. None (word search only)
    when the model is switched off or a document is missing from the cache."""
    if embeddings.embed(["probe"]) is None:
        return None
    from .generate import RAG_VECTOR_CACHE
    cache = json.loads(RAG_VECTOR_CACHE.read_text()) if RAG_VECTOR_CACHE.exists() else {}
    if not all(t in cache for t in texts):
        return None
    return [cache[t] for t in texts]


def _index_for(conn) -> dict:
    global _index
    if _index is None:
        docs = build_documents(conn)
        terms = [Counter(retrieval.keywords(d["text"])) for d in docs]
        document_frequency = Counter(t for counts in terms for t in counts)
        _index = {
            "docs": docs, "terms": terms, "df": document_frequency,
            "avg_len": sum(sum(c.values()) for c in terms) / len(terms),
            # Pre-computed by the generator (data/rag_embeddings.json).
            "vectors": _vectors([d["text"] for d in docs]),
        }
    return _index


def _bm25(index: dict, words: list[str]) -> list[float]:
    """Classic BM25 word score, the same family as Relate's full-text index."""
    n = len(index["docs"])
    scores = []
    for counts in index["terms"]:
        length = sum(counts.values())
        score = 0.0
        for w in set(words):
            if counts[w]:
                idf = math.log(1 + (n - index["df"][w] + 0.5) / (index["df"][w] + 0.5))
                score += idf * counts[w] * 2.2 / (counts[w] + 1.2 * (0.25 + 0.75 * length / index["avg_len"]))
        scores.append(score)
    return scores


def search(conn, question: str, k: int = 10) -> dict:
    """Top-k documents for the question, by fused word + meaning rank."""
    index = _index_for(conn)
    rankings = []
    word_scores = _bm25(index, retrieval.keywords(question))
    rankings.append([i for i in sorted(range(len(word_scores)), key=lambda i: -word_scores[i])
                     if word_scores[i] > 0])
    query_vector = embeddings.embed([question]) if index["vectors"] else None
    if query_vector:
        q = query_vector[0]
        sims = [sum(a * b for a, b in zip(q, v)) for v in index["vectors"]]
        rankings.append(sorted(range(len(sims)), key=lambda i: -sims[i]))
    fused = Counter()
    for ranking in rankings:
        for rank, i in enumerate(ranking[:50], start=1):
            fused[i] += 1 / (RRF_K + rank)
    top = [index["docs"][i] for i, _ in sorted(fused.items(), key=lambda x: (-x[1], x[0]))[:k]]
    return {"mode": "hybrid" if len(rankings) == 2 else "fulltext", "documents": top}


def compare(conn, question: str, results: list, k: int = 10) -> dict:
    """Plain RAG's top-k documents versus Ripple's graph answer (`results`
    from queries.port_closure / vessel_outage) for the same question."""
    found = search(conn, question, k)
    docs = found["documents"]
    rag_shipments = {d["shipment"] for d in docs if d["shipment"]}
    rag_customers = {d["customer_id"] for d in docs if d["customer_id"]}

    graph_shipments = {r["shipment"] for res in results for r in res["impacted"]}
    graph_customers = {r["customer_id"] for res in results for r in res["impacted"]}
    second_order = {r["customer_id"] for res in results for r in res["downstream"]} - graph_customers
    return {
        "question": question, "k": k, "mode": found["mode"], "documents": docs,
        "graph": {"shipments": len(graph_shipments), "customers": len(graph_customers),
                  "second_order_customers": len(second_order), "paths": len(graph_shipments)},
        "plain_rag": {
            "shipments_found": len(rag_shipments & graph_shipments),
            "shipments_wrong": len(rag_shipments - graph_shipments),  # named, but not delayed
            "customers_found": len(rag_customers & graph_customers),
            "second_order_found": len(rag_customers & second_order),
            "paths": 0,  # documents have no relationships to follow
        },
        "missed_shipments": sorted(graph_shipments - rag_shipments),
        "wrong_shipments": sorted(rag_shipments - graph_shipments),
    }


if __name__ == "__main__":
    from . import agent, db
    question = " ".join(sys.argv[1:]) or "Port of Rotterdam closed for 3 days"
    conn = db.connect()
    try:
        out = agent.compare_with_plain_rag(conn, question)
    finally:
        conn.close()
    g, r = out["graph"], out["plain_rag"]
    print(f"\nQ: {question}   (plain RAG: top {out['k']} documents, {out['mode']} search)\n")
    print(f"{'':28}{'Ripple (graph)':>16}{'Plain RAG':>12}")
    print(f"{'Delayed shipments found':28}{g['shipments']:>16}{r['shipments_found']:>12}")
    print(f"{'Shipments named, not delayed':28}{0:>16}{r['shipments_wrong']:>12}")
    print(f"{'Customers affected found':28}{g['customers']:>16}{r['customers_found']:>12}")
    print(f"{'Second-order customers':28}{g['second_order_customers']:>16}{r['second_order_found']:>12}")
    print(f"{'Explained by a path':28}{g['paths']:>16}{r['paths']:>12}")
    print("\nPlain RAG retrieved:")
    for d in out["documents"]:
        print(f"  [{d['kind']}] {d['text'][:110]}")
