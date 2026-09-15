import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parents[1] / "native_host"))
from contracts import WorkflowContract, CommandSpec
from orchestrator import Orchestrator


def test_policy_path_inspection_is_low_risk():
    from policy import classify
    assert classify('printenv PATH').level == 'low'
    assert classify('printf "%s\\n" "$PATH"').level == 'low'


def test_approved_index_bypasses_reapproval_once(tmp_path, monkeypatch):
    events=[]; orch=Orchestrator(events.append); orch.config["workspace_root"]=str(tmp_path); orch.config["auto_run_low_risk"]=True
    contract=WorkflowContract(version=1,phase="CP-0",stage="BOOTSTRAP",summary="approval regression",decision_required=False,decision_reason="",downloads=[],commands=[CommandSpec(cmd='python3 -c "print(123)"',cwd='.',purpose='run approved command')],success_conditions=["exit 0"],next_step="done")
    sent=[]; monkeypatch.setattr(orch,"_send_result_to_chatgpt",sent.append)
    orch._run_command_and_continue(contract,0,approved_index=0)
    assert not orch.pending; assert any(e.get("badge")=="PASS" for e in events); assert sent
