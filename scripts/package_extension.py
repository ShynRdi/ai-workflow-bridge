#!/usr/bin/env python3
from __future__ import annotations
import json, zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; EXT=ROOT/"extension"; DIST=ROOT/"dist"
version=json.loads((EXT/"manifest.json").read_text(encoding="utf-8"))["version"]; DIST.mkdir(exist_ok=True)
out=DIST/f"ai-workflow-bridge-extension-{version}.zip"
with zipfile.ZipFile(out,"w",zipfile.ZIP_DEFLATED) as zf:
    for path in sorted(EXT.rglob("*")):
        if path.is_file(): zf.write(path,path.relative_to(EXT))
print(out)
