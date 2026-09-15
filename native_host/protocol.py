from __future__ import annotations

import json
import struct
import sys
from typing import Any


def read_message() -> dict[str, Any] | None:
    raw_length = sys.stdin.buffer.read(4)
    if not raw_length:
        return None
    if len(raw_length) != 4:
        raise EOFError("Truncated native messaging length prefix")
    (length,) = struct.unpack("=I", raw_length)
    if length > 8 * 1024 * 1024:
        raise ValueError(f"Native message too large: {length}")
    raw = sys.stdin.buffer.read(length)
    if len(raw) != length:
        raise EOFError("Truncated native messaging payload")
    return json.loads(raw.decode("utf-8"))


def write_message(message: dict[str, Any]) -> None:
    raw = json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    sys.stdout.buffer.write(struct.pack("=I", len(raw)))
    sys.stdout.buffer.write(raw)
    sys.stdout.buffer.flush()
