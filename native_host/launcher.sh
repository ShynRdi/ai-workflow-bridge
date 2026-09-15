#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
if [[ -x /bin/bash ]]; then
  INTERACTIVE_PATH="$({ /bin/bash -ic 'printf "__AWB_PATH__=%s\\n" "$PATH"' 2>/dev/null || true; } | sed -n 's/^__AWB_PATH__=//p' | tail -n 1)"
  if [[ -n "${INTERACTIVE_PATH:-}" ]]; then export PATH="$INTERACTIVE_PATH"; fi
fi
exec /usr/bin/env python3 "$HERE/native_host.py"
