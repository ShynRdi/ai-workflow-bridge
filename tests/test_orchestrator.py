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


def test_extract_roadmap_preserves_machine_readable_acceptance_criteria():
    text = """
<<<AI_WORKFLOW_ROADMAP>>>
{
  "phases": [
    {
      "id": "P0",
      "title": "Foundation",
      "stages": ["BOOT", "TEST"],
      "acceptance_criteria": {
        "BOOT": [
          "Service starts",
          "Health endpoint returns success"
        ],
        "TEST": [
          "Required tests pass"
        ],
        "UNKNOWN": [
          "ignored"
        ]
      }
    }
  ]
}
<<<END_AI_WORKFLOW_ROADMAP>>>
"""

    roadmap = (
        Orchestrator.extract_roadmap(
            text
        )
    )

    assert roadmap is not None

    assert roadmap[0][
        "acceptance_criteria"
    ] == {
        "BOOT": [
            "Service starts",
            "Health endpoint returns success",
        ],
        "TEST": [
            "Required tests pass",
        ],
    }


def test_start_prompt_requires_stage_acceptance_criteria():
    bridge = Orchestrator.__new__(
        Orchestrator
    )

    bridge.config = {
        "project_name": "Demo",
        "project_goal": "Build demo",
        "workspace_root": "/tmp/demo",
    }

    prompt = bridge.start_prompt()

    assert "acceptance_criteria" in prompt

    assert (
        "observable acceptance criteria"
        in prompt
    )


def test_controller_prompt_exposes_current_canonical_acceptance_criteria(
    tmp_path,
):
    from project_state import (
        initialize_project_state,
    )

    initialize_project_state(
        str(tmp_path),
        [
            {
                "id": "P0",
                "title": "Foundation",
                "stages": [
                    "BOOT",
                ],
                "acceptance_criteria": {
                    "BOOT": [
                        "Service starts successfully",
                        "Required health check passes",
                    ],
                },
            }
        ],
    )

    bridge = Orchestrator.__new__(
        Orchestrator
    )

    bridge.config = {
        "project_name": "Demo",
        "project_goal": "Build demo",
        "workspace_root": str(
            tmp_path
        ),
        "provider_id": "chatgpt",
        "model_label": "",
        "phase": "P0",
        "stage": "BOOT",
        "roadmap": [],
    }

    bridge.active_provider = "chatgpt"

    prompt = bridge.controller_prompt()

    assert (
        "Current stage acceptance criteria:"
        in prompt
    )

    assert (
        "- Service starts successfully"
        in prompt
    )

    assert (
        "- Required health check passes"
        in prompt
    )
