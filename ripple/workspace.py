"""The workspace: a writable copy of the graph for decisions and memory.

The committed store (data/ripple.relate) stays read-only: every judge and
the CI must see the same data. What users add goes to a copy of it in
.ripple/workspace.relate (ignored by git), so new nodes link to the real
ports, shipments and customers:

  Memory (the agent remembers its analyses):
    (:Episode {question, at, days, shipments, ...})-[:ABOUT]->(:Port | :Vessel)

  Live news (real events fetched by ripple.live):
    (:LiveAlert {source, text, severity, date, url})-[:MENTIONS]->(:Port)

  Decisions (a diversion the user chose to keep):
    (:Plan)-[:DIVERTS_FROM]->(:Port)      the closed port
    (:Plan)-[:DIVERTS_TO]->(:Port)        the fallback port
    (:Plan)-[:RESCUES {before, after}]->(:Shipment)

If the committed data changes (python -m ripple.generate), the copy no longer
matches it and is rebuilt from scratch, dropping its plans, episodes and live alerts.
"""

import hashlib
import os
import shutil
import tempfile
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

import relate

from . import db

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PATH = ROOT / ".ripple" / "workspace.relate"


def path() -> Path:
    return Path(os.environ.get("RIPPLE_WORKSPACE", DEFAULT_PATH))


def _fingerprint() -> str:
    """Identifies the committed data the copy was made from."""
    return hashlib.sha256((db.STORE_PATH / "graph.json").read_bytes()).hexdigest()


def _base_file(where: Path) -> Path:
    return where.parent / (where.name + ".base")


def ensure() -> Path:
    """Create the copy if missing or out of date; return its path."""
    where = path()
    base = _base_file(where)
    if where.exists() and base.exists() and base.read_text() == _fingerprint():
        return where
    try:
        where.parent.mkdir(parents=True, exist_ok=True)
    except OSError:  # read-only app folder: fall back to the temp folder
        os.environ["RIPPLE_WORKSPACE"] = str(Path(tempfile.gettempdir()) / "ripple" / "workspace.relate")
        return ensure()
    if where.exists():
        shutil.rmtree(where)
    shutil.copytree(db.STORE_PATH, where, ignore=shutil.ignore_patterns(".cypherlite.writer"))
    conn = _open()
    try:
        for label in ("Episode", "Plan", "LiveAlert"):
            conn.execute(f"CREATE CONSTRAINT {label.lower()}_id IF NOT EXISTS "
                         f"FOR (n:{label}) REQUIRE n.id IS UNIQUE")
    finally:
        conn.close()
    base.write_text(_fingerprint())
    return where


def _open(read_only: bool = False, attempts: int = 20):
    """One writer at a time: wait a little if another session is writing."""
    for attempt in range(attempts):
        try:
            return relate.connect(str(path()), read_only=read_only)
        except relate.OperationalError as error:
            if "lock" not in str(error).lower() or attempt == attempts - 1:
                raise
            time.sleep(0.1)


def _write(cypher: str, params: dict) -> None:
    ensure()
    conn = _open()
    try:
        conn.execute(cypher, params)
    finally:
        conn.close()  # checkpoints: the change is on disk


def _read(cypher: str, params: dict | None = None) -> list[dict]:
    ensure()
    conn = _open(read_only=True)
    try:
        return [dict(r) for r in conn.execute(cypher, params or {})]
    finally:
        conn.close()


def write(cypher: str, params: dict) -> None:
    """Run a write query on the workspace (used by the live news module)."""
    _write(cypher, params)


def read(cypher: str, params: dict | None = None) -> list[dict]:
    return _read(cypher, params)


# ------------------------------------------------------------------- memory

def record_episode(out: dict) -> str:
    """Remember one answered question of the agent (agent.answer's output)."""
    episode_id = "E-" + uuid.uuid4().hex[:8]
    results = out["results"]
    _write("""
        CREATE (e:Episode {id: $id, question: $question, at: $at, days: $days, start: $start,
                           planned_by: $planned_by, shipments: $shipments, customers: $customers,
                           value_at_risk_usd: $value})
        WITH e
        OPTIONAL MATCH (p:Port) WHERE p.code IN $ports
        WITH e, collect(p) AS ports
        OPTIONAL MATCH (v:Vessel) WHERE v.imo IN $vessels
        WITH e, ports, collect(v) AS vessels
        FOREACH (t IN ports + vessels | CREATE (e)-[:ABOUT]->(t))
    """, {
        "id": episode_id, "question": out["question"], "at": datetime.now(UTC),
        "days": out["plan"]["days"], "start": out["plan"]["start"], "planned_by": out["planned_by"],
        "shipments": sum(r["summary"]["shipments"] for r in results),
        "customers": sum(r["summary"]["customers"] for r in results),
        "value": sum(r["summary"]["value_at_risk_usd"] for r in results),
        "ports": out["plan"]["ports"], "vessels": out["plan"]["vessels"],
    })
    return episode_id


def recall(port_codes: list, vessel_imos: list, limit: int = 5) -> list[dict]:
    """Earlier analyses about any of these ports or vessels, newest first."""
    return _read("""
        MATCH (e:Episode)-[:ABOUT]->(t)
        WHERE t.code IN $ports OR t.imo IN $vessels
        RETURN DISTINCT e.id AS id, e.question AS question, e.at AS at, e.days AS days,
               e.shipments AS shipments, e.customers AS customers,
               COLLECT { MATCH (e)-[:ABOUT]->(x) RETURN x.name ORDER BY x.name } AS about
        ORDER BY at DESC LIMIT $limit
    """, {"ports": port_codes, "vessels": vessel_imos, "limit": limit})


# ---------------------------------------------------------------- decisions

def save_plan(sim: dict, question: str) -> str:
    """Keep a diversion (mitigation.simulate_diversion's output) as a Plan."""
    plan_id = "P-" + uuid.uuid4().hex[:8]
    rescued = [{"shipment": r["shipment"], "before": r["delay_before"], "after": r["delay_after"]}
               for r in sim["shipments"] if r["delay_after"] < r["delay_before"]]
    _write("""
        MATCH (closed:Port {code: $closed}), (fallback:Port {code: $fallback})
        CREATE (pl:Plan {id: $id, question: $question, created_at: $at, days: $days,
                         shipments_rescued: $rescued_count, breaches_avoided: $breaches,
                         value_protected_usd: $value, extra_sea_km: $sea_km, extra_road_km: $road_km}),
               (pl)-[:DIVERTS_FROM]->(closed), (pl)-[:DIVERTS_TO]->(fallback)
        WITH pl
        UNWIND $rows AS row
        MATCH (s:Shipment {id: row.shipment})
        CREATE (pl)-[:RESCUES {delay_before: row.before, delay_after: row.after}]->(s)
    """, {
        "id": plan_id, "question": question, "at": datetime.now(UTC),
        "closed": sim["closed"]["code"], "fallback": sim["fallback"]["code"], "days": sim["closed"]["days"],
        "rescued_count": len(rescued), "breaches": sim["breaches_avoided"],
        "value": sim["value_protected_usd"], "sea_km": sim["extra_sea_km"], "road_km": sim["extra_road_km"],
        "rows": rescued,
    })
    return plan_id


def list_plans() -> list[dict]:
    """The decision log, newest first, with the customers each plan protects
    (a two-hop query from the plan through the shipments it rescues)."""
    return _read("""
        MATCH (pl:Plan)-[:DIVERTS_FROM]->(closed:Port), (pl)-[:DIVERTS_TO]->(fallback:Port)
        RETURN pl.id AS id, pl.created_at AS created_at, pl.question AS question, pl.days AS days,
               closed.name AS closed, fallback.name AS fallback,
               pl.shipments_rescued AS shipments_rescued, pl.breaches_avoided AS breaches_avoided,
               pl.value_protected_usd AS value_protected_usd,
               COLLECT { MATCH (pl)-[:RESCUES]->(:Shipment)-[:FOR]->(c:Customer)
                         RETURN DISTINCT c.name ORDER BY c.name } AS customers_protected
        ORDER BY created_at DESC
    """)


def clear() -> None:
    """Forget all episodes and plans (the copy is rebuilt on next use)."""
    where = path()
    if where.exists():
        shutil.rmtree(where)
    _base_file(where).unlink(missing_ok=True)
