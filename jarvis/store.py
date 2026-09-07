"""Local SQLite-backed storage for Jarvis.

Two concerns share one file (default: ~/.jarvis/jarvis.db, override with
JARVIS_DB_PATH) but are kept in separate tables and separate Python classes
because they answer different questions:

  - ContextStore ("what did we just talk about"): short-term conversational
    continuity — what was asked, which agent handled it, when. This is NOT
    permanent knowledge; Friday's vault is the permanent store. Jarvis's
    context here is expected to be pruned/rotated eventually (not done in
    v1 — see README "v1 placeholders").

  - AuditLog ("did anything private ever leave this machine"): a privacy/
    compliance trail of every dispatch *decision* — agent, tier, timestamp,
    and whether it was allowed or refused — written for every dispatch
    attempt regardless of outcome, so a future Wall-E agent can audit it.
    This is append-only and is not meant to be pruned casually.

Both are intentionally simple (stdlib sqlite3, no ORM) since v1 doesn't
need more than that.
"""

from __future__ import annotations

import datetime
import json
import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


def default_db_path() -> Path:
    override = os.environ.get("JARVIS_DB_PATH")
    if override:
        return Path(override)
    return Path.home() / ".jarvis" / "jarvis.db"


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


class ContextStore:
    """Short-term memory: what was asked, which agent handled it, when."""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or default_db_path()
        self._conn = _connect(self.db_path)
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS context_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                request_text TEXT NOT NULL,
                agent TEXT NOT NULL,
                tier TEXT NOT NULL,
                result_summary TEXT
            )
            """
        )
        self._conn.commit()

    def record(
        self,
        request_text: str,
        agent: str,
        tier: str,
        result_summary: Optional[str] = None,
        timestamp: Optional[str] = None,
    ) -> int:
        ts = timestamp or datetime.datetime.now(datetime.timezone.utc).isoformat()
        cur = self._conn.execute(
            "INSERT INTO context_entries (timestamp, request_text, agent, tier, "
            "result_summary) VALUES (?, ?, ?, ?, ?)",
            (ts, request_text, agent, tier, result_summary),
        )
        self._conn.commit()
        return cur.lastrowid

    def recent(self, limit: int = 10) -> list[sqlite3.Row]:
        cur = self._conn.execute(
            "SELECT * FROM context_entries ORDER BY id DESC LIMIT ?", (limit,)
        )
        return cur.fetchall()

    def is_reachable(self) -> bool:
        try:
            self._conn.execute("SELECT 1")
            return True
        except sqlite3.Error:
            return False

    def close(self) -> None:
        self._conn.close()


class AuditLog:
    """Append-only privacy/compliance audit trail: one row per dispatch
    decision (allowed or refused), for a future Wall-E agent to read."""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or default_db_path()
        self._conn = _connect(self.db_path)
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS audit_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                agent TEXT NOT NULL,
                tier TEXT NOT NULL,
                allowed INTEGER NOT NULL,
                reason TEXT,
                detail TEXT
            )
            """
        )
        self._conn.commit()

    def record(
        self,
        agent: str,
        tier: str,
        allowed: bool,
        reason: str = "",
        detail: Optional[dict] = None,
        timestamp: Optional[str] = None,
    ) -> int:
        ts = timestamp or datetime.datetime.now(datetime.timezone.utc).isoformat()
        cur = self._conn.execute(
            "INSERT INTO audit_entries (timestamp, agent, tier, allowed, reason, "
            "detail) VALUES (?, ?, ?, ?, ?, ?)",
            (ts, agent, tier, int(allowed), reason, json.dumps(detail or {})),
        )
        self._conn.commit()
        return cur.lastrowid

    def recent(self, limit: int = 10) -> list[sqlite3.Row]:
        cur = self._conn.execute(
            "SELECT * FROM audit_entries ORDER BY id DESC LIMIT ?", (limit,)
        )
        return cur.fetchall()

    def close(self) -> None:
        self._conn.close()
