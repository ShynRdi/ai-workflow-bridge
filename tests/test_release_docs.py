from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_public_docs_and_runtime_versions_are_aligned_with_04():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    guide = (ROOT / "docs" / "USER_GUIDE.md").read_text(encoding="utf-8")
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    manifest = (ROOT / "extension" / "manifest.json").read_text(encoding="utf-8")
    content = (ROOT / "extension" / "content.js").read_text(encoding="utf-8")
    sidepanel = (ROOT / "extension" / "sidepanel.html").read_text(encoding="utf-8")

    import json
    assert json.loads(manifest)["version"] == "0.4"
    assert 'const CONTENT_VERSION = "0.4"' in content
    assert "AI WORKFLOW BRIDGE · 0.4" in sidepanel
    assert "Public Preview 0.4" in readme
    assert "AI Workflow Bridge 0.4" in guide
    assert "## [0.4] - 2026-11-23" in changelog
    assert "Public Preview 0.3.6" not in readme
    assert "Isolated Development" in changelog and "0.3.6" in changelog
    assert "## [0.3.5] - 2026-11-15" in changelog
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


def test_release_docs_preserve_git_aware_checkpoint_safety_boundary():
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

    assert "## [0.4] - 2026-11-23" in combined
    assert "git-aware" in combined
    assert "checkpoint_id" in combined
    assert "head" in combined
    assert "index" in combined
    assert "human review" in combined
    assert "never rewrites" in combined
    assert ".git" in combined

    assert "Public Preview 0.4" in readme


    guide_lower = guide.lower()

    assert "exact checkpoint id" in guide_lower
    assert "git evidence" in guide_lower
    assert "git review required" in guide_lower
    assert "never rewrites head" in guide_lower
    assert "manual git review is required" in guide_lower


def test_unreleased_structured_review_docs_preserve_human_gate():
    combined = "\n".join(
        (ROOT / name).read_text(encoding="utf-8")
        for name in [
            "README.md",
            "CHANGELOG.md",
            "docs/ROADMAP.md",
            "docs/SECURITY_MODEL.md",
            "docs/USER_GUIDE.md",
        ]
    ).lower()

    for phrase in [
        "structured stage",
        "accept stage",
        "exact review",
        "stale",
        "command success",
        ".ai-workflow",
        "read-only git",
    ]:
        assert phrase in combined


def test_unreleased_policy_profile_docs_preserve_security_boundaries():
    combined = "\n".join(
        (ROOT / name).read_text(encoding="utf-8")
        for name in ["CHANGELOG.md", "README.md", "docs/ROADMAP.md", "docs/SECURITY_MODEL.md", "docs/USER_GUIDE.md"]
    ).lower()
    for phrase in [
        "per-project", "balanced", "strict", "isolated development",
        "stale", "llm", "execution isolation", "v0.4", ".ai-workflow/policy.json",
    ]:
        assert phrase in combined


def test_v04_release_security_and_roadmap_wording_is_precise():
    readme = (ROOT / "README.md").read_text(encoding="utf-8").lower()
    guide = (ROOT / "docs" / "USER_GUIDE.md").read_text(encoding="utf-8").lower()
    security = (ROOT / "docs" / "SECURITY_MODEL.md").read_text(encoding="utf-8").lower()
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8").lower()
    roadmap = (ROOT / "docs" / "ROADMAP.md").read_text(encoding="utf-8").lower()
    combined = "\n".join([readme, guide, security, changelog, roadmap])
    for phrase in [
        "policy decides whether a command may execute",
        "network=none",
        "local images only",
        "docker daemon remains trusted",
        "not a perfect hostile-code or multi-tenant boundary",
        "host credentials and environment are not forwarded",
        "docker.sock",
        "fsynced before docker launch",
        "full 64-character",
        "same-name replacement",
        "no command is automatically replayed",
    ]:
        assert phrase in combined
    assert "## 0.4 — execution isolation (implemented in public preview 0.4)" in roadmap
    assert "## 0.4.x — structured capabilities" in roadmap
