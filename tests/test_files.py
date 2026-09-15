import sys
import tempfile
import zipfile
from pathlib import Path
import pytest
sys.path.insert(0, str(Path(__file__).parents[1] / "native_host"))


def _reload(monkeypatch, td):
    monkeypatch.setenv("AI_WORKFLOW_BRIDGE_HOME", str(Path(td) / "app"))
    import importlib, config, files
    importlib.reload(config); importlib.reload(files)
    return files


def test_zip_traversal_detection(monkeypatch):
    with tempfile.TemporaryDirectory() as td:
        files = _reload(monkeypatch, td)
        archive = Path(td) / "bad.zip"
        with zipfile.ZipFile(archive, "w") as zf: zf.writestr("../escape.txt", "nope")
        with pytest.raises(ValueError, match="suspicious"):
            files.quarantine_downloads([{"filename": str(archive), "label": "bad"}])


def test_download_size_limit(monkeypatch):
    with tempfile.TemporaryDirectory() as td:
        files = _reload(monkeypatch, td)
        files.MAX_SINGLE_DOWNLOAD_BYTES = 10
        blob = Path(td) / "large.bin"; blob.write_bytes(b"x" * 11)
        with pytest.raises(ValueError, match="exceeds safety limit"):
            files.quarantine_downloads([{"filename": str(blob)}])


def test_zip_uncompressed_limit(monkeypatch):
    with tempfile.TemporaryDirectory() as td:
        files = _reload(monkeypatch, td)
        files.MAX_ZIP_UNCOMPRESSED_BYTES = 8
        archive = Path(td) / "large.zip"
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_STORED) as zf: zf.writestr("x.txt", "123456789")
        with pytest.raises(ValueError, match="uncompressed size"):
            files.quarantine_downloads([{"filename": str(archive)}])
