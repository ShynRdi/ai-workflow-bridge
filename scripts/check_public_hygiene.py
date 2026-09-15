#!/usr/bin/env python3
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIP_DIRS = {".git", ".venv", "dist", "build", "__pycache__", "node_modules"}
SKIP_SUFFIXES = {".pyc", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".zip"}
PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("private key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("Telegram-style token", re.compile(r"\b\d{8,}:[A-Za-z0-9_-]{20,}\b")),
    ("personal development path", re.compile(r"/home/(?:shynrdi|shayan)(?:/|\b)", re.I)),
    ("known private IPv4", re.compile(r"\b(?:192\.168\.150\.|85\.9\.108\.)\d+\b")),
]
ALLOWED_SECRET_ASSIGNMENT_FILES = {"scripts/check_public_hygiene.py", "native_host/redaction.py"}
SECRET_ASSIGNMENT = re.compile(r"(?i)\b(?:api[_-]?key|token|password|secret)\b\s*[:=]\s*[\"'][^\"']{8,}[\"']")


def iter_files():
    for path in ROOT.rglob("*"):
        if not path.is_file() or any(part in SKIP_DIRS for part in path.parts) or path.suffix.lower() in SKIP_SUFFIXES: continue
        yield path


def main() -> int:
    failures: list[str] = []
    for path in iter_files():
        rel = path.relative_to(ROOT).as_posix()
        try: text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError: continue
        for label, pattern in PATTERNS:
            if pattern.search(text): failures.append(f"{rel}: matched {label}")
        if rel not in ALLOWED_SECRET_ASSIGNMENT_FILES and SECRET_ASSIGNMENT.search(text): failures.append(f"{rel}: looks like a hard-coded secret assignment")
    forbidden = [p for p in ROOT.rglob("*") if p.name in {"__pycache__", ".pytest_cache"}]
    failures.extend(f"{p.relative_to(ROOT)}: generated cache should not be committed" for p in forbidden)
    if failures:
        print("Public hygiene check FAILED:", file=sys.stderr)
        for item in failures: print(f"- {item}", file=sys.stderr)
        return 1
    print("Public hygiene check PASS"); return 0


if __name__ == "__main__": raise SystemExit(main())
