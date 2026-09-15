from __future__ import annotations
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; HOST=ROOT/"native_host"
if str(HOST) not in sys.path: sys.path.insert(0,str(HOST))
from orchestrator import Orchestrator


def test_controller_prompt_keeps_download_dir_literal_and_lifecycle_rules():
    bridge=Orchestrator.__new__(Orchestrator); bridge.config={"phase":"19","stage":"C","workspace_root":"/tmp/project","provider_id":"chatgpt"}; bridge.active_provider="chatgpt"
    prompt=bridge.controller_prompt()
    assert "${AI_WORKFLOW_DOWNLOAD_DIR}" in prompt; assert "phase=19, stage=C" in prompt; assert "<<<AI_WORKFLOW>>>" in prompt; assert "/tmp/project" in prompt; assert "COURSE CHANGE" in prompt; assert "<<<AI_WORKFLOW_PROJECT_DONE>>>" in prompt; assert "CAPTCHA" in prompt


def test_start_prompt_is_planning_only_and_has_ready_marker():
    bridge=Orchestrator.__new__(Orchestrator); bridge.config={"project_name":"Demo","project_goal":"Build a safe demo","phase":"P0","stage":"PLAN","workspace_root":"/tmp/demo"}
    prompt=bridge.start_prompt(); assert "PLAN ONLY" in prompt; assert "READY_TO_ARM" in prompt; assert "Build a safe demo" in prompt
