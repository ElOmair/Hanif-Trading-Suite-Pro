import subprocess
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "deploy_mnt.sh"


def test_deploy_script_has_valid_bash_syntax():
    result = subprocess.run(["bash", "-n", str(SCRIPT)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_deploy_script_refuses_dirty_tree_by_default():
    text = SCRIPT.read_text(encoding="utf-8")
    assert "git status --porcelain" in text
    assert "MNT_ALLOW_DIRTY_DEPLOY" in text


def test_deploy_script_runs_preflight_before_worker_restart():
    text = SCRIPT.read_text(encoding="utf-8")
    preflight = text.index("mnt_preflight.py")
    worker_restart = text.index('systemctl restart "${WORKER_SERVICE}"')
    assert preflight < worker_restart


def test_deploy_script_waits_for_health_and_heartbeat():
    text = SCRIPT.read_text(encoding="utf-8")
    assert "/api/health" in text
    assert "mnt_worker_status.json" in text
    assert "mnt_status.py" in text
