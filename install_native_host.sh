#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <CHROME_EXTENSION_ID>" >&2
  echo "Load extension/ in chrome://extensions first, then copy its ID." >&2
  exit 2
fi

EXT_ID="$1"
ROOT="$(cd "$(dirname "$0")" && pwd)"
HOST_NAME="io.github.shynrdi.ai_workflow_bridge"
HOST_DIR="$ROOT/native_host"
MANIFEST_JSON="$(cat <<JSON
{
  "name": "$HOST_NAME",
  "description": "AI Workflow Bridge local orchestrator",
  "path": "$HOST_DIR/launcher.sh",
  "type": "stdio",
  "allowed_origins": ["chrome-extension://$EXT_ID/"]
}
JSON
)"

install_manifest() {
  local dir="$1"
  mkdir -p "$dir"
  printf '%s\n' "$MANIFEST_JSON" > "$dir/$HOST_NAME.json"
  echo "Installed: $dir/$HOST_NAME.json"
}

case "$(uname -s)" in
  Linux*)
    install_manifest "$HOME/.config/google-chrome/NativeMessagingHosts"
    if [[ -d "$HOME/.config/chromium" ]]; then
      install_manifest "$HOME/.config/chromium/NativeMessagingHosts"
    fi
    ;;
  Darwin*)
    install_manifest "$HOME/Library/Application Support/Google/Chrome/NativeMessagingHosts"
    ;;
  *)
    echo "Automatic installer currently supports Linux and macOS." >&2
    exit 3
    ;;
esac

chmod +x "$HOST_DIR/launcher.sh" "$HOST_DIR/native_host.py"
echo
echo "Native host ready. Reload the extension in chrome://extensions."
