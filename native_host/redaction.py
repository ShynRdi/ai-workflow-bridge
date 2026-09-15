from __future__ import annotations

import re

_REDACT = "[REDACTED]"
_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?im)\b([A-Z0-9_]*(?:API[_-]?KEY|TOKEN|SECRET|PASSWORD|PASSWD|PRIVATE[_-]?KEY|ACCESS[_-]?KEY)[A-Z0-9_]*)\s*=\s*([^\s]+)"),
    re.compile(r"(?i)\b(Bearer)\s+[A-Za-z0-9._~+/=-]{12,}"),
    re.compile(r"\b\d{8,}:[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----[\s\S]*?-----END (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
)


def redact_text(value: str) -> str:
    text = str(value or "")
    for pattern in _PATTERNS:
        if pattern.pattern.startswith("(?im)\\b("):
            text = pattern.sub(lambda m: f"{m.group(1)}={_REDACT}", text)
        elif "Bearer" in pattern.pattern:
            text = pattern.sub(lambda m: f"{m.group(1)} {_REDACT}", text)
        else:
            text = pattern.sub(_REDACT, text)
    return text
