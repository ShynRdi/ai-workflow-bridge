from __future__ import annotations

import re

_REDACT = "[REDACTED]"
_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?im)\b([A-Z0-9_]*(?:API[_-]?KEY|TOKEN|SECRET|PASSWORD|PASSWD|PRIVATE[_-]?KEY|ACCESS[_-]?KEY)[A-Z0-9_]*)\s*=\s*([^\s]+)"),
    re.compile(r"(?i)\b(Bearer|Basic)\s+[A-Za-z0-9._~+/=-]{12,}"),
    re.compile(r"\b\d{8,}:[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----[\s\S]*?-----END (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"\b(?:github_pat_[A-Za-z0-9_]{20,}|gh[pousr]_[A-Za-z0-9_]{20,})\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"(?i)(https?://)([^\s/@:]+):([^\s/@]+)@"),
    re.compile(r"(?i)([?&](?:api[_-]?key|access[_-]?token|token|secret|password)=)([^&#\s]+)"),
)


def redact_text(value: str) -> str:
    text = str(value or "")
    for pattern in _PATTERNS:
        source = pattern.pattern
        if source.startswith("(?im)\\b("):
            text = pattern.sub(lambda m: f"{m.group(1)}={_REDACT}", text)
        elif "Bearer|Basic" in source:
            text = pattern.sub(lambda m: f"{m.group(1)} {_REDACT}", text)
        elif source.startswith("(?i)(https?://)"):
            text = pattern.sub(lambda m: f"{m.group(1)}{_REDACT}:{_REDACT}@", text)
        elif source.startswith("(?i)([?&]"):
            text = pattern.sub(lambda m: f"{m.group(1)}{_REDACT}", text)
        else:
            text = pattern.sub(_REDACT, text)
    return text
