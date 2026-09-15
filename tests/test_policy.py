import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parents[1]/"native_host"))
from policy import classify


def test_read_only_inspection_is_low_risk():
    assert classify("git diff --check").level == "low"
    assert classify("git status --short").level == "low"


def test_project_code_execution_requires_approval():
    assert classify("python3 -m pytest -q").level == "approval"
    assert classify("pytest -q").level == "approval"
    assert classify("npm test").level == "approval"
    assert classify("pnpm run build").level == "approval"
    assert classify("make check").level == "approval"
    assert classify("eslint .").level == "approval"


def test_requires_approval():
    assert classify("git push origin main").level=="approval"; assert classify("./repair_stage_c.sh").level=="approval"


def test_blocked():
    assert classify("sudo apt install x").level=="blocked"; assert classify("rm -rf /tmp/example").level=="blocked"; assert classify("git reset --hard HEAD~1").level=="blocked"


def test_runtime_discovery_is_low_risk():
    assert classify("whereis node").level=="low"; assert classify("whereis npm").level=="low"


def test_find_mutating_actions_are_not_auto_run():
    assert classify("find . -delete").level=="approval"; assert classify("find . -exec echo {} \\;").level=="approval"


def test_sensitive_credential_paths_are_blocked():
    assert classify("cat ~/.ssh/id_rsa").level=="blocked"; assert classify("cat /etc/shadow").level=="blocked"; assert classify("cat $HOME/.aws/credentials").level=="blocked"


def test_arbitrary_environment_dump_requires_approval():
    assert classify("env").level=="approval"; assert classify("printenv").level=="approval"; assert classify("printenv API_KEY").level=="approval"; assert classify("printenv PATH").level=="low"; assert classify('echo "$API_KEY"').level=="approval"; assert classify('printf "%s\\n" "$PATH"').level=="low"


def test_low_risk_read_outside_workspace_requires_approval(tmp_path):
    workspace=tmp_path/"workspace"; workspace.mkdir(); assert classify("cat /etc/hosts",str(workspace)).level=="approval"; assert classify("cat ./README.md",str(workspace)).level=="low"
