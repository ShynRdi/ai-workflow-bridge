from __future__ import annotations

import hashlib
import shutil
import stat
import uuid
import zipfile
from pathlib import Path
from typing import Any
from config import APP_DIR, ensure_app_dir

MAX_FILES_PER_BUNDLE = 10
MAX_SINGLE_DOWNLOAD_BYTES = 100 * 1024 * 1024
MAX_TOTAL_DOWNLOAD_BYTES = 250 * 1024 * 1024
MAX_ZIP_ENTRIES = 5000
MAX_ZIP_UNCOMPRESSED_BYTES = 500 * 1024 * 1024
MAX_ZIP_MEMBER_BYTES = 150 * 1024 * 1024
MAX_ZIP_COMPRESSION_RATIO = 200


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def zip_inventory(path: Path, limit: int = 200) -> dict[str, Any] | None:
    if not zipfile.is_zipfile(path):
        return None
    with zipfile.ZipFile(path) as zf:
        infos = zf.infolist()
        if len(infos) > MAX_ZIP_ENTRIES:
            raise ValueError(f"Archive contains too many entries: {len(infos)} > {MAX_ZIP_ENTRIES}")
        suspicious: list[str] = []
        symlinks: list[str] = []
        total_uncompressed = 0
        for info in infos:
            name = info.filename
            if name.startswith("/") or ".." in Path(name).parts:
                suspicious.append(name)
            mode = (info.external_attr >> 16) & 0xFFFF
            if stat.S_ISLNK(mode):
                symlinks.append(name)
            total_uncompressed += int(info.file_size or 0)
            if info.file_size > MAX_ZIP_MEMBER_BYTES:
                raise ValueError(f"Archive member is too large: {name}")
            compressed = max(1, int(info.compress_size or 0))
            ratio = float(info.file_size or 0) / compressed
            if info.file_size > 1024 * 1024 and ratio > MAX_ZIP_COMPRESSION_RATIO:
                raise ValueError(f"Archive member has suspicious compression ratio: {name}")
        if total_uncompressed > MAX_ZIP_UNCOMPRESSED_BYTES:
            raise ValueError("Archive uncompressed size exceeds safety limit")
        if suspicious:
            raise ValueError(f"Archive contains suspicious traversal paths: {suspicious[:5]}")
        if symlinks:
            raise ValueError(f"Archive contains symbolic links: {symlinks[:5]}")
        return {
            "entries": [i.filename for i in infos[:limit]],
            "entry_count": len(infos),
            "suspicious_paths": suspicious[:50],
            "symlinks": symlinks[:50],
            "total_uncompressed_bytes": total_uncompressed,
        }


def quarantine_downloads(files: list[dict[str, Any]]) -> dict[str, Any]:
    if len(files) > MAX_FILES_PER_BUNDLE:
        raise ValueError(f"Too many downloaded files: {len(files)} > {MAX_FILES_PER_BUNDLE}")
    ensure_app_dir()
    run_id = uuid.uuid4().hex[:12]
    root = APP_DIR / "runs" / run_id / "downloads"
    root.mkdir(parents=True, exist_ok=False)
    copied: list[dict[str, Any]] = []
    total_bytes = 0
    try:
        for item in files:
            source = Path(str(item.get("filename") or "")).expanduser().resolve()
            if not source.is_file():
                raise FileNotFoundError(f"Downloaded file is missing: {source}")
            size = source.stat().st_size
            if size > MAX_SINGLE_DOWNLOAD_BYTES:
                raise ValueError(f"Downloaded file exceeds safety limit: {source.name}")
            total_bytes += size
            if total_bytes > MAX_TOTAL_DOWNLOAD_BYTES:
                raise ValueError("Downloaded bundle exceeds total safety limit")
            destination = root / source.name
            if destination.exists():
                destination = root / f"{destination.stem}-{uuid.uuid4().hex[:6]}{destination.suffix}"
            shutil.copy2(source, destination)
            inv = zip_inventory(destination)
            copied.append({
                "source": str(source), "path": str(destination), "name": destination.name,
                "sha256": sha256_file(destination), "size": destination.stat().st_size,
                "zip_inventory": inv, "label": item.get("label") or destination.name,
            })
    except Exception:
        shutil.rmtree(root.parent, ignore_errors=True)
        raise
    return {"run_id": run_id, "download_dir": str(root), "files": copied}
