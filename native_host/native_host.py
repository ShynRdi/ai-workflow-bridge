#!/usr/bin/env python3
from __future__ import annotations
import logging, sys, threading
from typing import Any
from config import LOG_PATH, ensure_app_dir
from orchestrator import Orchestrator
from protocol import read_message, write_message
ensure_app_dir()
try: LOG_PATH.touch(exist_ok=True); LOG_PATH.chmod(0o600)
except OSError: pass
logging.basicConfig(filename=LOG_PATH, level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
write_lock=threading.Lock()
def emit(message: dict[str, Any]) -> None:
    with write_lock: write_message(message)
def main() -> int:
    orchestrator=Orchestrator(emit); emit({"kind":"host_status","connected":True,"text":"Native host started"})
    while True:
        try:
            message=read_message()
            if message is None: return 0
            orchestrator.handle(message)
        except Exception as error:
            logging.exception("native host loop error")
            try: emit({"kind":"error","text":f"Native host error: {error}"})
            except Exception: return 1
if __name__ == "__main__": sys.exit(main())
