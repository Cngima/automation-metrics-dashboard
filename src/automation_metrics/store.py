"""SQLite storage: raw records exactly as synced, normalised runs and incidents, and a sync log.

Sync is incremental: a record is rewritten only when its content hash changes.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .classify import AgentRun, Classifier

SCHEMA = """
CREATE TABLE IF NOT EXISTS raw_records (
    key TEXT PRIMARY KEY,
    data TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    first_seen TEXT NOT NULL,
    last_changed TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS agent_runs (
    key TEXT PRIMARY KEY,
    agent TEXT NOT NULL,
    run_date TEXT NOT NULL,
    status TEXT NOT NULL,
    outcome TEXT NOT NULL,
    pillar TEXT,
    topic TEXT,
    platforms_ok TEXT,
    notes TEXT
);
CREATE TABLE IF NOT EXISTS incidents (
    run_key TEXT NOT NULL REFERENCES agent_runs(key) ON DELETE CASCADE,
    category TEXT NOT NULL,
    label TEXT NOT NULL,
    severity TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sync_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started TEXT NOT NULL,
    finished TEXT,
    source TEXT NOT NULL,
    fetched INTEGER DEFAULT 0,
    inserted INTEGER DEFAULT 0,
    updated INTEGER DEFAULT 0,
    unchanged INTEGER DEFAULT 0,
    error TEXT
);
CREATE INDEX IF NOT EXISTS idx_runs_agent_date ON agent_runs(agent, run_date);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _hash(data: dict) -> str:
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


class Store:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript(SCHEMA)

    def close(self) -> None:
        self.conn.close()

    def start_sync(self, source: str) -> int:
        cur = self.conn.execute("INSERT INTO sync_log (started, source) VALUES (?, ?)", (_now(), source))
        self.conn.commit()
        return cur.lastrowid

    def finish_sync(self, sync_id: int, counts: dict, error: str | None = None) -> None:
        self.conn.execute(
            "UPDATE sync_log SET finished=?, fetched=?, inserted=?, updated=?, unchanged=?, error=? WHERE id=?",
            (
                _now(),
                counts.get("fetched", 0),
                counts.get("inserted", 0),
                counts.get("updated", 0),
                counts.get("unchanged", 0),
                error,
                sync_id,
            ),
        )
        self.conn.commit()

    def upsert_records(self, records: list[dict], classifier: Classifier) -> dict:
        """Store raw records and (re)build the runs and incidents of any record that is new or changed."""
        counts = {"fetched": len(records), "inserted": 0, "updated": 0, "unchanged": 0}
        now = _now()
        for rec in records:
            key, data = rec["key"], rec.get("data") or {}
            h = _hash(data)
            row = self.conn.execute("SELECT content_hash FROM raw_records WHERE key=?", (key,)).fetchone()
            if row and row["content_hash"] == h:
                counts["unchanged"] += 1
                continue
            if row:
                self.conn.execute(
                    "UPDATE raw_records SET data=?, content_hash=?, last_changed=? WHERE key=?",
                    (json.dumps(data), h, now, key),
                )
                counts["updated"] += 1
            else:
                self.conn.execute(
                    "INSERT INTO raw_records (key, data, content_hash, first_seen, last_changed) VALUES (?,?,?,?,?)",
                    (key, json.dumps(data), h, now, now),
                )
                counts["inserted"] += 1
            self._replace_run(key, classifier.to_run(rec))
        self.conn.commit()
        return counts

    def _replace_run(self, key: str, run: AgentRun | None) -> None:
        self.conn.execute("DELETE FROM agent_runs WHERE key=?", (key,))
        if run is None:
            return
        self.conn.execute(
            "INSERT INTO agent_runs (key, agent, run_date, status, outcome, pillar, topic, platforms_ok, notes) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (
                run.key,
                run.agent,
                run.run_date.isoformat(),
                run.status,
                run.outcome,
                run.pillar,
                run.topic,
                ",".join(run.platforms_ok),
                run.notes,
            ),
        )
        self.conn.executemany(
            "INSERT INTO incidents (run_key, category, label, severity) VALUES (?,?,?,?)",
            [(key, i.category, i.label, i.severity) for i in run.incidents],
        )

    def rebuild(self, classifier: Classifier) -> None:
        """Re-classify every stored record, e.g. after the incident rules change."""
        for row in self.conn.execute("SELECT key, data FROM raw_records").fetchall():
            self._replace_run(row["key"], classifier.to_run({"key": row["key"], "data": json.loads(row["data"])}))
        self.conn.commit()

    def runs(self) -> list[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM agent_runs ORDER BY run_date, key").fetchall()

    def incident_rows(self) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT i.*, r.agent, r.run_date FROM incidents i JOIN agent_runs r ON r.key = i.run_key"
        ).fetchall()

    def last_sync(self) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM sync_log ORDER BY id DESC LIMIT 1").fetchone()
