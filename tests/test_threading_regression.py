from __future__ import annotations
import threading
from storage import Store

def test_store_can_record_event_from_worker_thread():
    store=Store(); errors=[]
    def worker():
        try: store.event("contract",{"ok":True})
        except Exception as exc: errors.append(exc)
    thread=threading.Thread(target=worker); thread.start(); thread.join(timeout=3); assert not thread.is_alive(); assert errors==[]
