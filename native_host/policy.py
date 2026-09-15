from __future__ import annotations

import re
import shlex
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PolicyDecision:
    level: str  # low | approval | blocked
    reason: str


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
    (r"\bgit\s+push\b", "publishes changes to a remote repository"),
    (r"\bgit\s+(merge|rebase|cherry-pick)\b", "changes git history or branch state"),
    (r"\b(pip|pip3|uv|poetry|npm|pnpm|yarn|bun)\s+(install|add|remove|update|upgrade)\b", "changes dependencies"),
    (r"\b(apt|apt-get|dnf|yum|pacman|brew)\s+", "changes system packages"),
    (r"\bdocker\s+(compose\s+)?(down|rm|rmi|system\s+prune|volume\s+rm)\b", "can remove containers/images/volumes"),
    (r"\b(alembic|django-admin|manage\.py)\b.*\b(migrate|upgrade|downgrade)\b", "changes database schema"),
    (r"\b(curl|wget)\b[^\n]*\|\s*(sh|bash)\b", "executes remote content directly"),
    (r"\bssh\b|\bscp\b|\brsync\b[^\n]*:", "accesses another machine"),
]

SENSITIVE_PATH_PATTERNS = (
    r"(?:~|\$HOME|\$\{HOME\}|/home/[^/]+|/root)/(?:\.ssh|\.gnupg|\.aws|\.azure|\.kube)(?:/|\b)",
    r"(?:~|\$HOME|\$\{HOME\}|/home/[^/]+|/root)/\.config/(?:gcloud|gh)(?:/|\b)",
    r"(?:~|\$HOME|\$\{HOME\}|/home/[^/]+|/root)/(?:\.netrc|\.git-credentials|\.pypirc)(?:\b|$)",
    r"/etc/(?:shadow|gshadow|sudoers)(?:\b|/)",
    r"/proc/(?:self|\d+)/environ(?:\b|$)",
    r"(?:~|\$HOME|\$\{HOME\}|/home/[^/]+|/root)/\.config/(?:google-chrome|chromium)(?:/|\b)",
)

LOW_PREFIXES = (
    "pytest", "python -m pytest", "python3 -m pytest",
    "python -m compileall", "python3 -m compileall",
    "git status", "git diff", "git log", "git show", "git rev-parse",
    "ls", "pwd", "find ", "grep ", "rg ", "cat ", "head ", "tail ",
    "ruff ", "mypy ", "pyright ", "eslint ", "npm test", "npm run test",
    "pnpm test", "yarn test", "make test", "make check",
    "node --version", "npm --version", "pnpm --version", "corepack --version",
    "command -v ", "which ", "whereis ", "type ", "test ",
)

SAFE_PRINTENV_KEYS = {"PATH", "HOME", "SHELL", "USER", "LOGNAME", "PWD", "LANG", "LC_ALL", "NVM_DIR"}


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
    for pattern, reason in BLOCK_PATTERNS:
        if re.search(pattern, lower):
            return PolicyDecision("blocked", reason)
    if _sensitive_path(command):
        return PolicyDecision("blocked", "command references a protected credential or account-data path")
    if lower == "env" or lower.startswith("env "):
        return PolicyDecision("approval", "environment output may contain secrets")
    if lower.startswith("printenv"):
        parts = normalized.split(); keys = parts[1:]
        if not keys or any(key not in SAFE_PRINTENV_KEYS for key in keys):
            return PolicyDecision("approval", "printing arbitrary environment variables may expose secrets")
        return PolicyDecision("low", "prints allowlisted non-secret environment metadata")
    if lower.startswith(("echo ", "printf ")):
        variables = set(re.findall(r"\$\{?([A-Za-z_][A-Za-z0-9_]*)\}?", command))
        if variables and not variables.issubset(SAFE_PRINTENV_KEYS):
            return PolicyDecision("approval", "shell expansion may expose environment secrets")
        if variables:
            return PolicyDecision("low", "prints allowlisted environment metadata")
        return PolicyDecision("low", "prints static text")
    for pattern, reason in APPROVAL_PATTERNS:
        if re.search(pattern, lower):
            return PolicyDecision("approval", reason)
    if _secretish_workspace_reference(command):
        return PolicyDecision("approval", "command references a file that commonly contains secrets")
    if lower.startswith("find ") and re.search(r"(?:^|\s)-(?:delete|exec|execdir|ok|okdir)(?:\s|$)", lower):
        return PolicyDecision("approval", "find action can modify files or execute commands")
    if re.search(r"(?:&&|\|\||[;|<>`]|\$\(|[\r\n])", command):
        return PolicyDecision("approval", "compound shell syntax requires review")
    if lower.startswith(LOW_PREFIXES):
        if _path_escapes_workspace(command, workspace_root):
            return PolicyDecision("approval", "command references a path outside the configured workspace")
        return PolicyDecision("low", "read-only verification/test command")
    if lower.startswith("./") or lower.startswith("bash ") or lower.startswith("sh "):
        return PolicyDecision("approval", "local script execution can modify the workspace")
    return PolicyDecision("approval", "command is not in the low-risk allowlist")
