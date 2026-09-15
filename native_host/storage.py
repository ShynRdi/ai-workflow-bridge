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
            self.db.execute("UPDATE approvals SET status=? WHERE approval_id=?", (decision, approval_id)); self.db.commit()
