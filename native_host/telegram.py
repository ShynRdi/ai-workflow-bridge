from __future__ import annotations

import json
import threading
import time
import urllib.request
from typing import Callable


class TelegramClient:
    def __init__(self, config_getter: Callable[[], dict], decision_callback: Callable[[str, str], None]) -> None:
        self.config_getter = config_getter
        self.decision_callback = decision_callback
        self.stop_event = threading.Event()
        self.offset = 0
        self.thread = threading.Thread(target=self._poll_loop, daemon=True, name="telegram-poll")
        self.thread.start()

    def _api(self, method: str, payload: dict) -> dict:
        config = self.config_getter(); token = str(config.get("bot_token") or "").strip()
        if not token: return {"ok": False, "description": "not configured"}
        url = f"https://api.telegram.org/bot{token}/{method}"
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=35) as response:
            return json.loads(response.read().decode("utf-8"))

    def send_report(self, text: str) -> None:
        config = self.config_getter(); chat_id = str(config.get("chat_id") or "").strip()
        if not chat_id or not config.get("bot_token"): return
        try: self._api("sendMessage", {"chat_id": chat_id, "text": text[:4000], "disable_web_page_preview": True})
        except Exception: pass

    def send_approval(self, approval_id: str, summary: str, command: str, impact: str) -> None:
        config = self.config_getter(); chat_id = str(config.get("chat_id") or "").strip()
        if not chat_id or not config.get("bot_token"): return
        text = f"🟡 DECISION REQUIRED\n\n{summary}\n\nCommand:\n{command}\n\n{impact}"[:3500]
        keyboard = {"inline_keyboard": [[{"text": "✅ Approve once", "callback_data": f"awb:a:{approval_id}"}, {"text": "❌ Reject", "callback_data": f"awb:r:{approval_id}"}]]}
        try: self._api("sendMessage", {"chat_id": chat_id, "text": text, "reply_markup": keyboard, "disable_web_page_preview": True})
        except Exception: pass

    def _poll_loop(self) -> None:
        while not self.stop_event.is_set():
            config = self.config_getter()
            if not config.get("bot_token") or not config.get("chat_id"):
                time.sleep(3); continue
            try:
                result = self._api("getUpdates", {"offset": self.offset, "timeout": 20, "allowed_updates": ["callback_query"]})
                for update in result.get("result", []):
                    self.offset = max(self.offset, int(update.get("update_id", 0)) + 1)
                    query = update.get("callback_query") or {}; data = str(query.get("data") or "")
                    if not data.startswith("awb:"): continue
                    _, action, approval_id = data.split(":", 2); decision = "approve" if action == "a" else "reject"
                    self.decision_callback(approval_id, decision)
                    callback_id = query.get("id")
                    if callback_id:
                        try: self._api("answerCallbackQuery", {"callback_query_id": callback_id, "text": decision.title()})
                        except Exception: pass
            except Exception:
                time.sleep(3)
