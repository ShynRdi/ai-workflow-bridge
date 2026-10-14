from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Any

from checkpoint import (
    CHECKPOINT_STATUSES,
    validate_checkpoint_metadata,
    validate_checkpoint_transition,
)
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
            CREATE TABLE IF NOT EXISTS checkpoints (
              checkpoint_id TEXT PRIMARY KEY,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              status TEXT NOT NULL,
              workspace_root TEXT NOT NULL,
              payload TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS checkpoints_workspace_created
              ON checkpoints(workspace_root, created_at DESC);
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

    def put_checkpoint(
        self,
        payload: dict[str, Any],
    ) -> str:
        validate_checkpoint_metadata(
            payload
        )

        checkpoint_id = str(
            payload["checkpoint_id"]
        )

        created_at = str(
            payload["created_at"]
        )

        status = str(
            payload["status"]
        )

        workspace_root = str(
            payload["workspace_root"]
        )

        updated_at = now_iso()

        encoded = json.dumps(
            payload,
            ensure_ascii=False,
        )

        with self.lock:
            self.db.execute(
                """
                INSERT INTO checkpoints(
                  checkpoint_id,
                  created_at,
                  updated_at,
                  status,
                  workspace_root,
                  payload
                )
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(checkpoint_id) DO UPDATE SET
                  updated_at=excluded.updated_at,
                  status=excluded.status,
                  workspace_root=excluded.workspace_root,
                  payload=excluded.payload
                """,
                (
                    checkpoint_id,
                    created_at,
                    updated_at,
                    status,
                    workspace_root,
                    encoded,
                ),
            )

            self.db.commit()

        return checkpoint_id

    def get_checkpoint(
        self,
        checkpoint_id: str,
    ) -> dict[str, Any] | None:
        with self.lock:
            row = self.db.execute(
                """
                SELECT
                  checkpoint_id,
                  created_at,
                  updated_at,
                  status,
                  workspace_root,
                  payload
                FROM checkpoints
                WHERE checkpoint_id=?
                """,
                (
                    str(checkpoint_id),
                ),
            ).fetchone()

        if row is None:
            return None

        try:
            payload = json.loads(
                row["payload"]
            )
        except (
            TypeError,
            json.JSONDecodeError,
        ):
            return None

        if not isinstance(payload, dict):
            return None

        payload = dict(payload)

        payload["checkpoint_id"] = str(
            row["checkpoint_id"]
        )

        payload["created_at"] = str(
            row["created_at"]
        )

        payload["updated_at"] = str(
            row["updated_at"]
        )

        payload["status"] = str(
            row["status"]
        )

        payload["workspace_root"] = str(
            row["workspace_root"]
        )

        return payload

    def transition_checkpoint_status(
        self,
        checkpoint_id: str,
        *,
        expected_status: str,
        new_status: str,
    ) -> bool:
        expected = str(
            expected_status or ""
        ).strip()

        target = str(
            new_status or ""
        ).strip()

        validate_checkpoint_transition(
            expected,
            target,
        )

        with self.lock:
            row = self.db.execute(
                """
                SELECT status, payload
                FROM checkpoints
                WHERE checkpoint_id=?
                """,
                (
                    str(checkpoint_id),
                ),
            ).fetchone()

            if row is None:
                return False

            current = str(
                row["status"]
            )

            if current != expected:
                return False

            try:
                payload = json.loads(
                    row["payload"]
                )
            except (
                TypeError,
                json.JSONDecodeError,
            ) as error:
                raise ValueError(
                    "Checkpoint payload is corrupted"
                ) from error

            if not isinstance(
                payload,
                dict,
            ):
                raise ValueError(
                    "Checkpoint payload is corrupted"
                )

            payload["status"] = target

            updated_at = now_iso()

            cursor = self.db.execute(
                """
                UPDATE checkpoints
                SET
                  status=?,
                  updated_at=?,
                  payload=?
                WHERE
                  checkpoint_id=?
                  AND status=?
                """,
                (
                    target,
                    updated_at,
                    json.dumps(
                        payload,
                        ensure_ascii=False,
                    ),
                    str(checkpoint_id),
                    expected,
                ),
            )

            self.db.commit()

            return cursor.rowcount == 1

    def update_checkpoint_status(
        self,
        checkpoint_id: str,
        status: str,
    ) -> bool:
        target = str(
            status or ""
        ).strip()

        if target not in CHECKPOINT_STATUSES:
            raise ValueError(
                f"Invalid checkpoint status: {target}"
            )

        with self.lock:
            row = self.db.execute(
                """
                SELECT status
                FROM checkpoints
                WHERE checkpoint_id=?
                """,
                (
                    str(checkpoint_id),
                ),
            ).fetchone()

        if row is None:
            return False

        current = str(
            row["status"]
        )

        if current == target:
            return True

        return self.transition_checkpoint_status(
            checkpoint_id,
            expected_status=current,
            new_status=target,
        )

    def list_checkpoints(
        self,
        *,
        workspace_root: str | None = None,
        status: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []

        if workspace_root is not None:
            clauses.append(
                "workspace_root=?"
            )
            params.append(
                str(workspace_root)
            )

        if status is not None:
            value = str(
                status
            ).strip()

            if value not in CHECKPOINT_STATUSES:
                raise ValueError(
                    f"Invalid checkpoint status: {value}"
                )

            clauses.append(
                "status=?"
            )
            params.append(value)

        where = (
            " WHERE " + " AND ".join(clauses)
            if clauses
            else ""
        )

        bounded_limit = max(
            1,
            min(
                int(limit),
                500,
            ),
        )

        params.append(
            bounded_limit
        )

        query = (
            "SELECT checkpoint_id "
            "FROM checkpoints"
            f"{where} "
            "ORDER BY created_at DESC "
            "LIMIT ?"
        )

        with self.lock:
            rows = self.db.execute(
                query,
                tuple(params),
            ).fetchall()

        result: list[dict[str, Any]] = []

        for row in rows:
            checkpoint = self.get_checkpoint(
                str(
                    row["checkpoint_id"]
                )
            )

            if checkpoint is not None:
                result.append(
                    checkpoint
                )

        return result

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
