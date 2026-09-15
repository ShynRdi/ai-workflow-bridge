from __future__ import annotations

import re
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Any


RISK_ORDER = {"R0": 0, "R1": 1, "R2": 2, "R3": 3, "R4": 4}


@dataclass(frozen=True)
class PolicyDecision:
    level: str  # low | approval | blocked
    reason: str
    risk_level: str = "R2"


@dataclass(frozen=True)
class EffectiveRisk:
    level: str  # low | approval | blocked
    risk_level: str
    local_risk_level: str
    llm_risk_level: str | None
    reason: str
    escalated_by_llm: bool = False


BLOCK_PATTERNS = [
    (r"(^|\s)sudo(\s|$)", "sudo is never executed by the bridge"),
    (r"\brm\s+-[^\n]*r[^\n]*f", "recursive forced deletion is blocked"),
    (r"\bgit\s+reset\s+--hard\b", "destructive git reset is blocked"),
    (r"\bgit\s+clean\s+-[^\n]*f", "git clean -f is blocked"),
    (r"\bmkfs(?:\.|\s)", "filesystem formatting is blocked"),
    (r"\bdd\s+if=", "raw disk writes are blocked"),
    (r"\bshutdown\b|\breboot\b|\bpoweroff\b", "system power commands are blocked"),
    (r"\b(chmod|chown)\s+-R\s+/(?:\s|$)", "recursive root permission changes are blocked"),
]

APPROVAL_PATTERNS = [
    (r"\bgit\s+push\b", "publishes changes to a remote repository", "R3"),
    (r"\bgit\s+(merge|rebase|cherry-pick)\b", "changes git history or branch state", "R2"),
    (r"\b(pip|pip3|uv|poetry|npm|pnpm|yarn|bun)\s+(install|add|remove|update|upgrade)\b", "changes dependencies", "R2"),
    (r"\b(apt|apt-get|dnf|yum|pacman|brew)\s+", "changes system packages", "R3"),
    (r"\bdocker\s+(compose\s+)?(down|rm|rmi|system\s+prune|volume\s+rm)\b", "can remove containers/images/volumes", "R3"),
    (r"\b(alembic|django-admin|manage\.py)\b.*\b(migrate|upgrade|downgrade)\b", "changes database schema", "R3"),
    (r"\b(curl|wget)\b[^\n]*\|\s*(sh|bash)\b", "executes remote content directly", "R3"),
    (r"\bssh\b|\bscp\b|\brsync\b[^\n]*:", "accesses another machine", "R3"),
]

# These commands may look like verification, but they execute project-controlled code,
# plugins, scripts, or package hooks. They therefore require human approval.
PROJECT_CODE_EXECUTION_PATTERNS = [
    (r"^(?:python3?|py)\s+-m\s+pytest\b|^pytest\b", "test runner executes project-controlled Python code"),
    (r"^(?:npm|pnpm|yarn|bun)\s+(?:test|run\s+\S+)", "package script can execute project-controlled code"),
    (r"^make(?:\s|$)", "Make targets can execute arbitrary project commands"),
    (r"^(?:ruff|mypy|pyright|eslint)(?:\s|$)", "tooling may load project plugins/configuration and execute local code"),
    (r"^(?:python3?|node|ruby|perl)\s+[^-]", "interpreter invocation executes a project/local program"),
]

SENSITIVE_PATH_PATTERNS = (
    r"(?:~|\$HOME|\$\{HOME\}|/home/[^/]+|/root)/(?:\.ssh|\.gnupg|\.aws|\.azure|\.kube)(?:/|\b)",
    r"(?:~|\$HOME|\$\{HOME\}|/home/[^/]+|/root)/\.config/(?:gcloud|gh)(?:/|\b)",
    r"(?:~|\$HOME|\$\{HOME\}|/home/[^/]+|/root)/(?:\.netrc|\.git-credentials|\.pypirc)(?:\b|$)",
    r"/etc/(?:shadow|gshadow|sudoers)(?:\b|/)",
    r"/proc/(?:self|\d+)/environ(?:\b|$)",
    r"(?:~|\$HOME|\$\{HOME\}|/home/[^/]+|/root)/\.config/(?:google-chrome|chromium)(?:/|\b)",
)

# Only commands whose semantics are intrinsically inspection-oriented belong here.
LOW_PREFIXES = (
    "git status", "git diff", "git log", "git show", "git rev-parse",
    "ls", "pwd", "find ", "grep ", "rg ", "cat ", "head ", "tail ",
    "node --version", "npm --version", "pnpm --version", "corepack --version",
    "python --version", "python3 --version",
    "command -v ", "which ", "whereis ", "type ", "test ",
)

SAFE_PRINTENV_KEYS = {"PATH", "HOME", "SHELL", "USER", "LOGNAME", "PWD", "LANG", "LC_ALL", "NVM_DIR", "VIRTUAL_ENV"}


def _decision(level: str, reason: str, risk_level: str) -> PolicyDecision:
    return PolicyDecision(level=level, reason=reason, risk_level=risk_level)


def _sensitive_path(command: str) -> bool:
    return any(re.search(pattern, command, re.IGNORECASE) for pattern in SENSITIVE_PATH_PATTERNS)


def _secretish_workspace_reference(command: str) -> bool:
    lower = command.lower()
    if re.search(r"(?:^|[/\s'\"])\.env(?:\.[a-z0-9_-]+)?(?:$|[\s'\"])", lower):
        if not re.search(r"\.env\.(?:example|sample|template|dist)(?:$|[\s'\"])", lower):
            return True
    return bool(re.search(r"(?:^|[/\s'\"])(?:credentials(?:\.json)?|secrets?\.[a-z0-9_-]+|[^\s/]+\.(?:pem|key))(?:$|[\s'\"])", lower))


def _path_escapes_workspace(command: str, workspace_root: str) -> bool:
    if not workspace_root:
        return False
    root = Path(workspace_root).expanduser().resolve()
    try:
        tokens = shlex.split(command, posix=True)
    except ValueError:
        return True

    def candidate_value(token: str) -> str:
        if "=" in token and token.startswith("-"):
            return token.split("=", 1)[1]
        return token

    for raw in tokens[1:]:
        token = candidate_value(raw)
        if not token or token.startswith("-"):
            continue
        if token.startswith(("http://", "https://")):
            continue
        if token.startswith(("~/", "$HOME/", "${HOME}/")):
            return True
        path: Path | None = None
        if token.startswith("/"):
            path = Path(token)
        elif token.startswith(("../", "./")) or "/" in token:
            path = root / token
        else:
            maybe = root / token
            if maybe.exists() or maybe.is_symlink():
                path = maybe
        if path is None:
            continue
        try:
            path.expanduser().resolve().relative_to(root)
        except ValueError:
            return True
    return False


def classify(command: str, workspace_root: str = "") -> PolicyDecision:
    normalized = " ".join(command.strip().split())
    lower = normalized.lower()
    if not normalized:
        return _decision("blocked", "empty commands are never executed", "R4")
    for pattern, reason in BLOCK_PATTERNS:
        if re.search(pattern, lower):
            return _decision("blocked", reason, "R4")
    if _sensitive_path(command):
        return _decision("blocked", "command references a protected credential or account-data path", "R4")
    if lower == "env" or lower.startswith("env "):
        return _decision("approval", "environment output may contain secrets", "R3")
    if lower.startswith("printenv"):
        parts = normalized.split(); keys = parts[1:]
        if not keys or any(key not in SAFE_PRINTENV_KEYS for key in keys):
            return _decision("approval", "printing arbitrary environment variables may expose secrets", "R3")
        return _decision("low", "prints allowlisted non-secret environment metadata", "R0")
    if lower.startswith(("echo ", "printf ")):
        variables = set(re.findall(r"\$\{?([A-Za-z_][A-Za-z0-9_]*)\}?", command))
        if variables and not variables.issubset(SAFE_PRINTENV_KEYS):
            return _decision("approval", "shell expansion may expose environment secrets", "R3")
        if variables:
            return _decision("low", "prints allowlisted environment metadata", "R0")
        return _decision("low", "prints static text", "R0")
    for pattern, reason, risk_level in APPROVAL_PATTERNS:
        if re.search(pattern, lower):
            return _decision("approval", reason, risk_level)
    if _secretish_workspace_reference(command):
        return _decision("approval", "command references a file that commonly contains secrets", "R3")
    if lower.startswith("find ") and re.search(r"(?:^|\s)-(?:delete|exec|execdir|ok|okdir)(?:\s|$)", lower):
        return _decision("approval", "find action can modify files or execute commands", "R2")
    if re.search(r"(?:&&|\|\||[;|<>`]|\$\(|[\r\n])", command):
        return _decision("approval", "compound shell syntax requires review", "R2")
    for pattern, reason in PROJECT_CODE_EXECUTION_PATTERNS:
        if re.search(pattern, lower):
            return _decision("approval", reason, "R2")
    if lower.startswith(LOW_PREFIXES):
        if _path_escapes_workspace(command, workspace_root):
            return _decision("approval", "command references a path outside the configured workspace", "R2")
        return _decision("low", "bounded read-only inspection command", "R0")
    if lower.startswith("./") or lower.startswith("bash ") or lower.startswith("sh "):
        return _decision("approval", "local script execution can modify the workspace", "R2")
    return _decision("approval", "command is not in the low-risk allowlist", "R2")


def _llm_level(assessment: Any) -> str | None:
    value = getattr(assessment, "level", None)
    if value is None and isinstance(assessment, dict):
        value = assessment.get("level")
    value = str(value or "").upper().strip()
    return value if value in RISK_ORDER else None


def merge_risk(local: PolicyDecision, llm_assessment: Any = None) -> EffectiveRisk:
    llm = _llm_level(llm_assessment)
    local_rank = RISK_ORDER.get(local.risk_level, 2)
    llm_rank = RISK_ORDER.get(llm, -1) if llm else -1
    effective_rank = max(local_rank, llm_rank)
    effective_risk = next(level for level, rank in RISK_ORDER.items() if rank == effective_rank)
    escalated = llm is not None and llm_rank > local_rank

    if local.level == "blocked" or effective_risk == "R4":
        level = "blocked"
    elif local.level == "approval" or effective_rank >= RISK_ORDER["R2"]:
        level = "approval"
    else:
        level = "low"

    parts = [f"Local policy: {local.risk_level} — {local.reason}"]
    if llm:
        factors = getattr(llm_assessment, "factors", None)
        if factors is None and isinstance(llm_assessment, dict):
            factors = llm_assessment.get("factors")
        factor_text = "; ".join(str(x) for x in (factors or [])[:4])
        llm_text = f"LLM assessment: {llm}"
        if factor_text:
            llm_text += f" — {factor_text}"
        parts.append(llm_text)
    else:
        parts.append("LLM assessment: unavailable/invalid; local policy remains authoritative")
    if escalated:
        parts.append(f"Effective risk escalated to {effective_risk}; LLM assessments may only raise risk")

    return EffectiveRisk(
        level=level,
        risk_level=effective_risk,
        local_risk_level=local.risk_level,
        llm_risk_level=llm,
        reason="\n".join(parts),
        escalated_by_llm=escalated,
    )
