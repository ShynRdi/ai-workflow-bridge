from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_public_docs_are_aligned_with_034():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    guide = (ROOT / "docs" / "USER_GUIDE.md").read_text(encoding="utf-8")
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")

    assert "Public Preview 0.3.4" in readme
    assert "AI Workflow Bridge 0.3.4" in guide
    assert "## [0.3.4] - 2026-10-27" in changelog
    assert "RECOVERY_REQUIRED" in readme
    assert "Checkpoint and rollback" in changelog


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



def test_034_docs_do_not_overstate_rollback_guarantees():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    guide = (ROOT / "docs" / "USER_GUIDE.md").read_text(encoding="utf-8")
    security = (ROOT / "docs" / "SECURITY_MODEL.md").read_text(encoding="utf-8")

    combined = "\n".join(
        [
            readme,
            guide,
            security,
        ]
    ).lower()

    assert "workspace" in combined
    assert "checkpoint" in combined
    assert "rollback" in combined
    assert ".git" in combined
    assert ".ai-workflow" in combined
    assert "remote" in combined
    assert "database" in combined
    assert "system" in combined
    assert "not transactional" in combined
    assert "automatically retry" in combined


def test_unreleased_git_aware_checkpoint_docs_preserve_safety_boundary():
    readme = (
        ROOT /
        "README.md"
    ).read_text(
        encoding="utf-8"
    )

    roadmap = (
        ROOT /
        "docs" /
        "ROADMAP.md"
    ).read_text(
        encoding="utf-8"
    )

    guide = (
        ROOT /
        "docs" /
        "USER_GUIDE.md"
    ).read_text(
        encoding="utf-8"
    )

    security = (
        ROOT /
        "docs" /
        "SECURITY_MODEL.md"
    ).read_text(
        encoding="utf-8"
    )

    changelog = (
        ROOT /
        "CHANGELOG.md"
    ).read_text(
        encoding="utf-8"
    )

    combined = "\n".join(
        [
            readme,
            roadmap,
            guide,
            security,
            changelog,
        ]
    ).lower()

    assert "## [unreleased]" in combined
    assert "git-aware" in combined
    assert "checkpoint_id" in combined
    assert "head" in combined
    assert "index" in combined
    assert "human review" in combined
    assert "never rewrites" in combined
    assert ".git" in combined

    assert "Public Preview 0.3.4" in readme


    guide_lower = guide.lower()

    assert "exact checkpoint id" in guide_lower
    assert "git evidence" in guide_lower
    assert "git review required" in guide_lower
    assert "never rewrites head" in guide_lower
    assert "manual git review is required" in guide_lower
