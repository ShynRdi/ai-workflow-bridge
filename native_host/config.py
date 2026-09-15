from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

APP_DIR = Path(os.environ.get("AI_WORKFLOW_BRIDGE_HOME", Path.home() / ".config" / "ai-workflow-bridge"))
CONFIG_PATH = APP_DIR / "config.json"
STATE_PATH = APP_DIR / "state.json"
DB_PATH = APP_DIR / "bridge.sqlite3"
LOG_PATH = APP_DIR / "bridge.log"

DEFAULT_CONFIG: dict[str, Any] = {
    "project_name": "",
    "project_goal": "",
    "workspace_root": "",
    "phase": "",
    "stage": "",
    "roadmap": [],
    "provider_mode": "manual",
    "provider_id": "chatgpt",
    "model_label": "",
    "auto_run_low_risk": True,
    "min_turn_interval_seconds": 8,
    "max_turns_per_hour": 20,
    "max_turns_per_session": 25,
    "max_runtime_minutes": 90,
    "pause_on_provider_safety_signal": True,
    "allow_auto_provider_fallback": False,
    "bot_token": "",
    "chat_id": "",
    "require_clean_git": False,
    "command_timeout_seconds": 900,
    "max_output_chars": 24000,
}

def ensure_app_dir() -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    try: APP_DIR.chmod(0o700)
    except OSError: pass

def load_json(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    ensure_app_dir()
    if not path.exists(): return dict(default)
    try:
        data = json.loads(path.read_text(encoding="utf-8")); return {**default, **data}
    except Exception: return dict(default)

def save_json(path: Path, data: dict[str, Any]) -> None:
    ensure_app_dir(); tmp = path.with_suffix(path.suffix + ".tmp"); tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"); os.replace(tmp, path)
    try: path.chmod(0o600)
    except OSError: pass

def load_config() -> dict[str, Any]: return load_json(CONFIG_PATH, DEFAULT_CONFIG)
def save_config(patch: dict[str, Any]) -> dict[str, Any]:
    config = load_config()
    for key in DEFAULT_CONFIG:
        if key not in patch: continue
        if key == "bot_token" and not str(patch[key] or "").strip() and str(config.get("bot_token") or "").strip(): continue
        config[key] = patch[key]
    save_json(CONFIG_PATH, config); return config

def public_config(config: dict[str, Any]) -> dict[str, Any]:
    public = {k: v for k, v in config.items() if k != "bot_token"}; public["bot_token"] = ""; public["bot_configured"] = bool(str(config.get("bot_token") or "").strip()); return public
