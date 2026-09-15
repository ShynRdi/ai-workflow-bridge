#!/usr/bin/env python3
from __future__ import annotations
import json, tarfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; DIST=ROOT/"dist"
version=json.loads((ROOT/"extension"/"manifest.json").read_text(encoding="utf-8"))["version"]; DIST.mkdir(exist_ok=True)
out=DIST/f"ai-workflow-bridge-{version}.tar.gz"; skip={".git",".venv",".pytest_cache","__pycache__","dist","node_modules"}
with tarfile.open(out,"w:gz") as tf:
    for path in sorted(ROOT.rglob("*")):
        rel=path.relative_to(ROOT)
        if any(part in skip for part in rel.parts): continue
        tf.add(path,arcname=Path("ai-workflow-bridge")/rel,recursive=False)
print(out)
