from __future__ import annotations

import threading
import time
from typing import Any


class RunBudget:
    """Guarded session budget with restart-safe state export/restore."""

    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.reset("chatgpt")

    def reset(self, provider_id: str) -> None:
        with self.lock:
            now = time.time()
            self.provider_id = provider_id or "unknown"
            self.session_started_at = now
            self.turn_timestamps: list[float] = []
            self.last_turn_at = 0.0
            self.cooldown_until = 0.0
            self.block_reason = ""

    def set_provider(self, provider_id: str) -> None:
        with self.lock:
            if provider_id and provider_id != self.provider_id:
                self.reset(provider_id)

    def block(self, reason: str, seconds: float | None = None) -> None:
        with self.lock:
            self.block_reason = reason or "provider safety signal"
            self.cooldown_until = (time.time() + seconds) if seconds else float("inf")

    def clear_block(self) -> None:
        with self.lock:
            self.block_reason = ""
            self.cooldown_until = 0.0

    def export_state(self) -> dict[str, Any]:
        with self.lock:
            manual_block = self.cooldown_until == float("inf")

            return {
                "version": 1,
                "provider_id": str(self.provider_id or "unknown"),
                "session_started_at": float(self.session_started_at),
                "turn_timestamps": [
                    float(value)
                    for value in self.turn_timestamps
                ],
                "last_turn_at": float(self.last_turn_at),
                "cooldown_until": (
                    None
                    if manual_block
                    else float(self.cooldown_until)
                ),
                "manual_block": manual_block,
                "block_reason": str(self.block_reason or ""),
            }

    def restore_state(
        self,
        payload: dict[str, Any] | None,
    ) -> bool:
        if not isinstance(payload, dict):
            return False

        try:
            provider_id = str(
                payload.get("provider_id") or "unknown"
            )

            session_started_at = float(
                payload.get("session_started_at") or 0.0
            )

            if session_started_at <= 0:
                session_started_at = time.time()

            raw_turns = payload.get("turn_timestamps") or []

            turn_timestamps = [
                float(value)
                for value in raw_turns
                if isinstance(value, (int, float))
            ]

            last_turn_at = float(
                payload.get("last_turn_at") or 0.0
            )

            manual_block = bool(
                payload.get("manual_block")
            )

            raw_cooldown = payload.get("cooldown_until")

            cooldown_until = (
                float("inf")
                if manual_block
                else max(
                    0.0,
                    float(raw_cooldown or 0.0),
                )
            )

            block_reason = str(
                payload.get("block_reason") or ""
            )
        except (TypeError, ValueError):
            return False

        with self.lock:
            self.provider_id = provider_id
            self.session_started_at = session_started_at
            self.turn_timestamps = turn_timestamps
            self.last_turn_at = last_turn_at
            self.cooldown_until = cooldown_until
            self.block_reason = block_reason

        return True

    def decision(self, config: dict[str, Any]) -> dict[str, Any]:
        with self.lock:
            now = time.time()
            self.turn_timestamps = [t for t in self.turn_timestamps if now - t < 3600]
            max_session = int(config.get("max_turns_per_session", 25) or 25)
            max_hour = int(config.get("max_turns_per_hour", 20) or 20)
            max_runtime = float(config.get("max_runtime_minutes", 90) or 90)
            min_interval = max(3.0, float(config.get("min_turn_interval_seconds", 8) or 8))
            if self.cooldown_until > now:
                return {"allowed": False, "hard": True, "reason": self.block_reason or "provider safety cooldown", "delay": None}
            runtime_minutes = (now - self.session_started_at) / 60.0
            if runtime_minutes >= max_runtime:
                return {"allowed": False, "hard": True, "reason": f"session runtime budget reached ({max_runtime:g} min)", "delay": None}
            if len(self.turn_timestamps) >= max_hour:
                return {"allowed": False, "hard": True, "reason": f"hourly AI-turn budget reached ({max_hour})", "delay": None}
            if len(self.turn_timestamps) >= max_session:
                return {"allowed": False, "hard": True, "reason": f"session AI-turn budget reached ({max_session})", "delay": None}
            wait = max(0.0, min_interval - (now - self.last_turn_at)) if self.last_turn_at else 0.0
            return {"allowed": True, "hard": False, "reason": "", "delay": wait}

    def record_send(self) -> None:
        with self.lock:
            now = time.time(); self.last_turn_at = now; self.turn_timestamps.append(now)

    def public(self, config: dict[str, Any]) -> dict[str, Any]:
        with self.lock:
            now = time.time(); recent = [t for t in self.turn_timestamps if now - t < 3600]
            cooldown = None
            if self.cooldown_until == float("inf"): cooldown = "manual"
            elif self.cooldown_until > now: cooldown = self.cooldown_until
            return {"provider_id": self.provider_id, "session_turns": len(self.turn_timestamps), "turns_last_hour": len(recent), "runtime_minutes": max(0.0, (now - self.session_started_at) / 60.0), "cooldown_until": cooldown, "block_reason": self.block_reason}
