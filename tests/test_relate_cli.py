"""The committed store also opens with Relate's own CLI, read-only.
Skipped when the `relate` CLI is not installed (as in CI)."""

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from ripple import db

RELATE = shutil.which("relate") or str(Path.home() / ".local" / "bin" / "relate")
pytestmark = pytest.mark.skipif(not os.access(RELATE, os.X_OK), reason="relate CLI not installed")


def fingerprint(store: Path) -> dict:
    return {str(p.relative_to(store)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(store.rglob("*")) if p.is_file()}


def test_cli_reads_the_store_without_changing_it():
    before = fingerprint(db.STORE_PATH)
    run = subprocess.run(
        [RELATE, "--database", str(db.STORE_PATH), "--read-only", "--mode", "jsonl",
         "MATCH (:Port {name: 'Rotterdam'})<-[:CALLS_AT]-(r:Route) RETURN count(r) AS routes"],
        capture_output=True, text=True, timeout=60, env={**os.environ, "DO_NOT_TRACK": "1"})
    assert run.returncode == 0, run.stderr
    assert json.loads(run.stdout.strip().splitlines()[-1])["routes"] == 5
    assert fingerprint(db.STORE_PATH) == before


def test_the_replay_commands_shown_in_the_app_give_the_same_rows(tmp_path):
    """Every query of an answer, replayed with the command the app shows, returns
    as many rows from the CLI as it did from Python."""
    import shlex

    from ripple import queries
    store = tmp_path / "copy.relate"
    shutil.copytree(db.STORE_PATH, store)
    conn = db.connect()
    try:
        result = queries.port_closure(conn, "NLRTM", 3)
    finally:
        conn.close()
    for step in result["trace"]:
        command = queries.cli_command(step["cypher"], step["params"], store=str(store))
        args = shlex.split(command.replace("--mode table", "--mode jsonl"))
        run = subprocess.run([RELATE, *args[1:]], capture_output=True, text=True, timeout=60,
                             env={**os.environ, "DO_NOT_TRACK": "1"})
        assert run.returncode == 0, run.stderr
        assert sum(line.startswith("{") for line in run.stdout.splitlines()) == step["rows"], step["name"]
