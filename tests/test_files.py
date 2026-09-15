import sys
import tempfile
import zipfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parents[1] / "native_host"))


def test_zip_traversal_detection(monkeypatch):
    with tempfile.TemporaryDirectory() as td:
        monkeypatch.setenv("AI_WORKFLOW_BRIDGE_HOME", str(Path(td) / "app"))
        import importlib, config, files
        importlib.reload(config); importlib.reload(files)
        archive = Path(td) / "bad.zip"
        with zipfile.ZipFile(archive, "w") as zf: zf.writestr("../escape.txt", "nope")
        try: files.quarantine_downloads([{"filename": str(archive), "label": "bad"}])
        except ValueError as exc: assert "suspicious" in str(exc).lower()
        else: raise AssertionError("Traversal archive should be rejected")
