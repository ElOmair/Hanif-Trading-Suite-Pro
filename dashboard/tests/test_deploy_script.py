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


def test_deploy_script_uses_mnt_only_override_not_full_env_example():
    text = SCRIPT.read_text(encoding="utf-8")
    assert "mnt.env.example" in text
    assert 'MNT_ENV_FILE="${DASHBOARD_DIR}/mnt.env"' in text
    assert "cp .env.example .env" not in text
    assert "/home/airomair/Kronos/.env" in text


def test_deploy_script_does_not_source_credentials_as_shell_code():
    text = SCRIPT.read_text(encoding="utf-8")
    executable_lines = [
        line.strip()
        for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    assert not any(line.startswith("source ") for line in executable_lines)
    assert not any(line.startswith(". /home/airomair/Kronos/.env") for line in executable_lines)


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
