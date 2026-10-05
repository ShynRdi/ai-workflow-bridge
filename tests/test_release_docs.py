from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_public_docs_are_aligned_with_033():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    guide = (ROOT / "docs" / "USER_GUIDE.md").read_text(encoding="utf-8")
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")

    assert "Public Preview 0.3.3" in readme
    assert "AI Workflow Bridge 0.3.3" in guide
    assert "## [0.3.3] - 2026-10-05" in changelog
    assert "RECOVERY_REQUIRED" in readme
    assert "Crash-safe recovery and conversation identity" in changelog


def test_docs_cover_diagnostics_progress_and_active_tab_binding():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    guide = (ROOT / "docs" / "USER_GUIDE.md").read_text(encoding="utf-8")
    security = (ROOT / "docs" / "SECURITY_MODEL.md").read_text(encoding="utf-8")

    combined = "\n".join([readme, guide, security]).lower()

    assert "run diagnostics" in combined
    assert "progress" in combined
    assert "active" in combined
    assert "bound" in combined
    assert "does not request new provider permissions" in combined
