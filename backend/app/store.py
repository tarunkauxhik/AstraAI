"""Durable run records: the single source of truth for everything the API reports.

SQLite through the standard library, synchronous on purpose: RunManager relies on a state
change finishing before its next await, so exactly one of approval, rejection, extension,
expiry or shutdown can win for a run. Writes are single small rows on local disk.
"""

import sqlite3
from pathlib import Path

from app.runs import FINISHED_STATUSES, Run, RunStatus

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    -- Creation order, stable even when two runs share a timestamp.
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL,
    -- The whole Run as JSON; status is copied out, in the same write, only to query by it.
    data TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS runs_status ON runs (status);
"""


class RunStore:
    """Run records in one SQLite file (or ":memory:"), one connection per process."""

    def __init__(self, path: str | Path) -> None:
        # Autocommit: every statement is its own transaction, durable when it returns.
        self._db = sqlite3.connect(path, isolation_level=None)
        self._db.execute("PRAGMA journal_mode=WAL")
        # FULL: a write that returned (an approval answered with 202, say) also survives an OS
        # crash or power loss, not only a process crash. Writes are few, so the sync is cheap.
        self._db.execute("PRAGMA synchronous=FULL")
        self._db.execute("PRAGMA busy_timeout=5000")
        self._db.executescript(SCHEMA)

    def close(self) -> None:
        self._db.close()

    def put(self, run: Run) -> None:
        """Insert a run, or replace the stored one with the same id."""
        self._db.execute(
            "INSERT INTO runs (run_id, status, data) VALUES (?, ?, ?) "
            "ON CONFLICT (run_id) DO UPDATE SET status = excluded.status, "
            "data = excluded.data",
            (
                run.run_id,
                run.status,
                run.model_dump_json(exclude={"approval_required"}),
            ),
        )

    def get(self, run_id: str) -> Run | None:
        row = self._db.execute(
            "SELECT data FROM runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        return None if row is None else Run.model_validate_json(row[0])

    def with_status(self, *statuses: RunStatus) -> list[Run]:
        """Runs in any of these statuses, oldest first."""
        marks = ", ".join("?" * len(statuses))
        rows = self._db.execute(
            f"SELECT data FROM runs WHERE status IN ({marks}) ORDER BY seq", statuses
        )
        return [Run.model_validate_json(data) for (data,) in rows]

    def forget_finished(self, keep: int) -> None:
        """Delete the oldest finished runs beyond `keep` runs in total; never unfinished ones."""
        (total,) = self._db.execute("SELECT COUNT(*) FROM runs").fetchone()
        if total <= keep:
            return
        finished = sorted(FINISHED_STATUSES)
        marks = ", ".join("?" * len(finished))
        self._db.execute(
            f"DELETE FROM runs WHERE run_id IN (SELECT run_id FROM runs "
            f"WHERE status IN ({marks}) ORDER BY seq LIMIT ?)",
            (*finished, total - keep),
        )
