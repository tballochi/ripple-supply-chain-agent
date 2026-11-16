"""Open the Relate store and define its schema.

Relate is an embedded graph database: it runs inside this Python process and
persists to a directory. There is no server to start.
"""

import os
from pathlib import Path

import relate

# The store lives in the repo so the app works right after `git clone`.
STORE_PATH = Path(__file__).resolve().parent.parent / "data" / "ripple.relate"

# One uniqueness constraint per node label. Besides protecting against
# duplicates, each constraint gives Relate an index on the key property,
# so `MATCH (p:Port {code: $code})` is a lookup instead of a scan.
CONSTRAINTS = {
    "Port": "code",
    "Route": "id",
    "Vessel": "imo",
    "Shipment": "id",
    "Product": "sku",
    "Customer": "id",
    "Alert": "id",
}


def connect(read_only: bool = True) -> "relate.Connection":
    """Open the store. Readers (UI, agent) use read_only=True; only the
    generator writes."""
    if not read_only:
        # The JSON codec stores the graph as one readable graph.json file,
        # which is easier to inspect and to diff in git than Parquet.
        # It only applies when the store is first created.
        os.environ.setdefault("RELATE_SNAPSHOT_FORMAT", "json")
        STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    elif not STORE_PATH.exists():
        raise FileNotFoundError(
            f"No store at {STORE_PATH}. Run: python -m ripple.generate"
        )
    return relate.connect(str(STORE_PATH), read_only=read_only)


def create_schema(conn) -> None:
    for label, key in CONSTRAINTS.items():
        conn.execute(
            f"CREATE CONSTRAINT {label.lower()}_{key} IF NOT EXISTS "
            f"FOR (n:{label}) REQUIRE n.{key} IS UNIQUE"
        )


def create_search_indexes(conn, with_vectors: bool) -> None:
    """Indexes used to match free text against the news alerts.

    - Full-text index: finds alerts sharing words with the question (BM25).
    - Vector index: finds alerts with a similar meaning, even with no word
      in common. Needs the embeddings stored on each alert.
    """
    conn.execute("CREATE FULLTEXT INDEX alert_text IF NOT EXISTS FOR (a:Alert) ON EACH [a.text]")
    if with_vectors:
        from .embeddings import DIMENSIONS
        conn.execute(
            "CREATE VECTOR INDEX alert_embedding IF NOT EXISTS FOR (a:Alert) ON (a.embedding) "
            f"OPTIONS {{indexConfig: {{`vector.dimensions`: {DIMENSIONS}, "
            "`vector.similarity_function`: 'cosine'}}"
        )
