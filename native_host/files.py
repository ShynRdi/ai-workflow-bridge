from __future__ import annotations

import hashlib
import shutil
import uuid
import zipfile
from pathlib import Path
from typing import Any
from config import APP_DIR, ensure_app_dir

def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""): h.update(chunk)
    return h.hexdigest()

def zip_inventory(path: Path, limit: int = 200) -> dict[str, Any] | None:
    if not zipfile.is_zipfile(path): return None
    with zipfile.ZipFile(path) as zf:
        names = zf.namelist(); suspicious = [name for name in names if name.startswith("/") or ".." in Path(name).parts]
        return {"entries": names[:limit], "entry_count": len(names), "suspicious_paths": suspicious[:50]}

def quarantine_downloads(files: list[dict[str, Any]]) -> dict[str, Any]:
    ensure_app_dir(); run_id = uuid.uuid4().hex[:12]; root = APP_DIR / "runs" / run_id / "downloads"; root.mkdir(parents=True, exist_ok=False); copied=[]
    for item in files:
        source=Path(str(item.get("filename") or "")).expanduser().resolve()
        if not source.is_file(): raise FileNotFoundError(f"Downloaded file is missing: {source}")
        destination=root/source.name
        if destination.exists(): destination=root/f"{destination.stem}-{uuid.uuid4().hex[:6]}{destination.suffix}"
        shutil.copy2(source,destination); inv=zip_inventory(destination)
        if inv and inv["suspicious_paths"]: raise ValueError(f"Archive contains suspicious traversal paths: {inv['suspicious_paths'][:5]}")
        copied.append({"source":str(source),"path":str(destination),"name":destination.name,"sha256":sha256_file(destination),"size":destination.stat().st_size,"zip_inventory":inv,"label":item.get("label") or destination.name})
    return {"run_id":run_id,"download_dir":str(root),"files":copied}
