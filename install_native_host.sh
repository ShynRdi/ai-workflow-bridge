#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <CHROME_EXTENSION_ID>" >&2
  echo "Load extension/ in chrome://extensions first, then copy its ID." >&2
  exit 2
fi

EXT_ID="$1"

if [[ ! "$EXT_ID" =~ ^[a-p]{32}$ ]]; then
  echo "Invalid Chrome extension ID: $EXT_ID" >&2
  exit 2
fi

ROOT="$(cd "$(dirname "$0")" && pwd)"
HOST_NAME="io.github.shynrdi.ai_workflow_bridge"
SOURCE_HOST_DIR="$ROOT/native_host"

find_python() {
  local candidate
  local seen=""

  for candidate in \
    /opt/homebrew/bin/python3 \
    /usr/local/bin/python3 \
    "$(command -v python3 2>/dev/null || true)" \
    /usr/bin/python3
  do
    [[ -n "$candidate" ]] || continue
    [[ -x "$candidate" ]] || continue

    case ":$seen:" in
      *":$candidate:"*) continue ;;
    esac
    seen="${seen}:$candidate"

    case "$candidate" in
      */.venv/*|*/venv/*)
        continue
        ;;
    esac

    if "$candidate" -c \
      'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' \
      >/dev/null 2>&1
    then
      printf '%s\n' "$candidate"
      return 0
    fi
  done

  return 1
}

PYTHON_BIN="$(find_python || true)"

if [[ -z "$PYTHON_BIN" ]]; then
  echo "Python 3.11+ is required but no suitable python3 was found." >&2
  echo "Install Python 3.11+ and run this installer again." >&2
  exit 4
fi

write_manifest() {
  local dir="$1"
  local launcher_path="$2"
  local manifest_path="$dir/$HOST_NAME.json"

  mkdir -p "$dir"

  "$PYTHON_BIN" - \
    "$manifest_path" \
    "$HOST_NAME" \
    "$launcher_path" \
    "$EXT_ID" <<'PY'
import json
import sys
from pathlib import Path

manifest_path, host_name, launcher_path, extension_id = sys.argv[1:]

payload = {
    "name": host_name,
    "description": "AI Workflow Bridge local orchestrator",
    "path": launcher_path,
    "type": "stdio",
    "allowed_origins": [
        f"chrome-extension://{extension_id}/",
    ],
}

path = Path(manifest_path)
path.write_text(
    json.dumps(payload, indent=2) + "\n",
    encoding="utf-8",
)
PY

  chmod 600 "$manifest_path" 2>/dev/null || true
  echo "Installed manifest: $manifest_path"
}

case "$(uname -s)" in
  Linux*)
    chmod +x \
      "$SOURCE_HOST_DIR/launcher.sh" \
      "$SOURCE_HOST_DIR/native_host.py"

    write_manifest \
      "$HOME/.config/google-chrome/NativeMessagingHosts" \
      "$SOURCE_HOST_DIR/launcher.sh"

    if [[ -d "$HOME/.config/chromium" ]]; then
      write_manifest \
        "$HOME/.config/chromium/NativeMessagingHosts" \
        "$SOURCE_HOST_DIR/launcher.sh"
    fi
    ;;

  Darwin*)
    INSTALL_ROOT="$HOME/Library/Application Support/AI Workflow Bridge"
    INSTALLED_HOST_DIR="$INSTALL_ROOT/native_host"
    INSTALLED_LAUNCHER="$INSTALL_ROOT/launcher.sh"

    mkdir -p "$INSTALL_ROOT"
    chmod 700 "$INSTALL_ROOT" 2>/dev/null || true

    rm -rf "$INSTALLED_HOST_DIR"
    cp -R "$SOURCE_HOST_DIR" "$INSTALLED_HOST_DIR"

    find "$INSTALLED_HOST_DIR" \
      -type d -name '__pycache__' \
      -prune -exec rm -rf {} + 2>/dev/null || true

    find "$INSTALLED_HOST_DIR" \
      -type f \( -name '*.pyc' -o -name '*.pyo' \) \
      -exec rm -f {} + 2>/dev/null || true

    PYTHON_Q="$(printf '%q' "$PYTHON_BIN")"
    HOST_Q="$(printf '%q' "$INSTALLED_HOST_DIR/native_host.py")"

    {
      echo '#!/usr/bin/env bash'
      echo 'set -euo pipefail'
      printf 'exec %s %s\n' "$PYTHON_Q" "$HOST_Q"
    } > "$INSTALLED_LAUNCHER"

    chmod 755 "$INSTALLED_LAUNCHER"
    chmod 755 "$INSTALLED_HOST_DIR/native_host.py"

    if command -v xattr >/dev/null 2>&1; then
      xattr -dr com.apple.quarantine "$INSTALL_ROOT" 2>/dev/null || true
    fi

    write_manifest \
      "$HOME/Library/Application Support/Google/Chrome/NativeMessagingHosts" \
      "$INSTALLED_LAUNCHER"

    if [[ -d "$HOME/Library/Application Support/Chromium" ]]; then
      write_manifest \
        "$HOME/Library/Application Support/Chromium/NativeMessagingHosts" \
        "$INSTALLED_LAUNCHER"
    fi

    echo
    echo "Installed native host:"
    echo "  $INSTALL_ROOT"
    echo
    echo "Pinned Python:"
    echo "  $PYTHON_BIN"
    ;;

  *)
    echo "Automatic installer currently supports Linux and macOS." >&2
    exit 3
    ;;
esac

echo
echo "Native host ready."
echo "Reload AI Workflow Bridge in chrome://extensions."
