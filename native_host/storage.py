from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Any

from config import DB_PATH, ensure_app_dir


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class Store:
    def __init__(self) -> None:
        ensure_app_dir()
        self.lock = threading.RLock()
        self.db = sqlite3.connect(DB_PATH, check_same_thread=False)
        try: DB_PATH.chmod(0o600)
        except OSError: pass
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS events (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              created_at TEXT NOT NULL,
              kind TEXT NOT NULL,
              payload TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS approvals (
              approval_id TEXT PRIMARY KEY,
              created_at TEXT NOT NULL,
              status TEXT NOT NULL,
              payload TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS runtime_state (
              key TEXT PRIMARY KEY,
              updated_at TEXT NOT NULL,
              payload TEXT NOT NULL
            );
        """)
        self.db.commit()

    def event(self, kind: str, payload: dict[str, Any]) -> None:
        with self.lock:
            self.db.execute("INSERT INTO events(created_at, kind, payload) VALUES (?, ?, ?)", (now_iso(), kind, json.dumps(payload, ensure_ascii=False)))
            self.db.commit()

    def put_approval(self, approval_id: str, payload: dict[str, Any]) -> None:
        with self.lock:
            self.db.execute("INSERT OR REPLACE INTO approvals(approval_id, created_at, status, payload) VALUES (?, ?, 'pending', ?)", (approval_id, now_iso(), json.dumps(payload, ensure_ascii=False)))
            self.db.commit()

    def resolve_approval(self, approval_id: str, decision: str) -> None:
        with self.lock:
            self.db.execute(
                "UPDATE approvals SET status=? WHERE approval_id=?",
                (decision, approval_id),
            )
            self.db.commit()

    def put_runtime_state(
        self,
        key: str,
        payload: dict[str, Any],
    ) -> None:
        with self.lock:
            self.db.execute(
                """
                INSERT INTO runtime_state(key, updated_at, payload)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                  updated_at=excluded.updated_at,
                  payload=excluded.payload
                """,
                (
                    str(key),
                    now_iso(),
                    json.dumps(payload, ensure_ascii=False),
                ),
            )
            self.db.commit()

    def get_runtime_state(
        self,
        key: str,
    ) -> dict[str, Any] | None:
        with self.lock:
            row = self.db.execute(
                "SELECT payload FROM runtime_state WHERE key=?",
                (str(key),),
            ).fetchone()

        if row is None:
            return None

        try:
            payload = json.loads(row["payload"])
        except (TypeError, json.JSONDecodeError):
            return None

        return payload if isinstance(payload, dict) else None

    def clear_runtime_state(
        self,
        key: str,
    ) -> None:
        with self.lock:
            self.db.execute(
                "DELETE FROM runtime_state WHERE key=?",
                (str(key),),
            )
            self.db.commit()

    def expire_pending_approvals(self) -> None:
        with self.lock:
            self.db.execute(
                """
                UPDATE approvals
                SET status='expired'
                WHERE status='pending'
                """
            )
            self.db.commit()

    def list_pending_approvals(self) -> list[dict[str, Any]]:
        with self.lock:
            rows = self.db.execute(
                """
                SELECT approval_id, created_at, payload
                FROM approvals
                WHERE status='pending'
                ORDER BY created_at ASC
                """
            ).fetchall()

        result: list[dict[str, Any]] = []

        for row in rows:
            try:
                payload = json.loads(row["payload"])
            except (TypeError, json.JSONDecodeError):
                payload = {}

            if not isinstance(payload, dict):
                payload = {}

            result.append(
                {
                    "approval_id": str(row["approval_id"]),
                    "created_at": str(row["created_at"]),
                    **payload,
                }
            )

        return result
