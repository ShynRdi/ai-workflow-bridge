from __future__ import annotations

import threading
import time
from typing import Any


class RunBudget:
    """In-memory session budget. Conservative by design; browser/account signals always pause."""

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
