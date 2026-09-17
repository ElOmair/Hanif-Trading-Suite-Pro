#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="${MNT_REPO_ROOT:-/home/airomair/Hanif-Trading-Suite-Pro}"
DASHBOARD_DIR="${REPO_ROOT}/dashboard"
VENV_DIR="${MNT_VENV_DIR:-/home/airomair/kronos-venv}"
SYSTEMD_DIR="/etc/systemd/system"
DASHBOARD_SERVICE="hanif-dashboard.service"
WORKER_SERVICE="mnt-alert-worker.service"

log() {
  printf '\n[MnT deploy] %s\n' "$*"
}

fail() {
  printf '\n[MnT deploy] ERROR: %s\n' "$*" >&2
  exit 1
}

[[ -d "${REPO_ROOT}/.git" ]] || fail "Git repository not found at ${REPO_ROOT}"
[[ -d "${DASHBOARD_DIR}" ]] || fail "Dashboard directory not found at ${DASHBOARD_DIR}"
[[ -x "${VENV_DIR}/bin/python" ]] || fail "Python virtualenv missing at ${VENV_DIR}"
[[ -x "${VENV_DIR}/bin/pip" ]] || fail "pip missing at ${VENV_DIR}"

cd "${REPO_ROOT}"

if [[ -n "$(git status --porcelain)" && "${MNT_ALLOW_DIRTY_DEPLOY:-false}" != "true" ]]; then
  fail "Repository has uncommitted changes. Commit/stash them or set MNT_ALLOW_DIRTY_DEPLOY=true intentionally."
fi

log "Repository: $(git rev-parse --show-toplevel)"
log "Branch: $(git branch --show-current)"
log "Commit: $(git rev-parse --short HEAD)"

cd "${DASHBOARD_DIR}"

if [[ ! -f .env ]]; then
  log "Creating dashboard/.env from .env.example (existing Kronos/.env is also loaded by systemd)"
  cp .env.example .env
  chmod 600 .env
else
  log "Keeping existing dashboard/.env unchanged"
fi

log "Installing/updating dashboard Python dependencies in ${VENV_DIR}"
"${VENV_DIR}/bin/pip" install -r requirements.txt

log "Validating Python modules before service restart"
"${VENV_DIR}/bin/python" -m compileall -q .

log "Installing systemd units"
sudo install -m 0644 "${DASHBOARD_SERVICE}" "${SYSTEMD_DIR}/${DASHBOARD_SERVICE}"
sudo install -m 0644 "${WORKER_SERVICE}" "${SYSTEMD_DIR}/${WORKER_SERVICE}"
sudo systemctl daemon-reload

log "Enabling and restarting dashboard"
sudo systemctl enable "${DASHBOARD_SERVICE}" >/dev/null
sudo systemctl restart "${DASHBOARD_SERVICE}"

log "Waiting for local dashboard health"
healthy=false
for _ in $(seq 1 20); do
  if curl --fail --silent --show-error http://127.0.0.1:8080/api/health >/dev/null 2>&1; then
    healthy=true
    break
  fi
  sleep 1
done
[[ "${healthy}" == "true" ]] || {
  sudo systemctl status "${DASHBOARD_SERVICE}" --no-pager || true
  fail "Dashboard did not become healthy on http://127.0.0.1:8080/api/health"
}

log "Running MnT preflight before starting unattended worker"
"${VENV_DIR}/bin/python" mnt_preflight.py

log "Enabling and restarting alert supervisor"
sudo systemctl enable "${WORKER_SERVICE}" >/dev/null
sudo systemctl restart "${WORKER_SERVICE}"

log "Checking service state"
sudo systemctl is-active --quiet "${DASHBOARD_SERVICE}" || fail "${DASHBOARD_SERVICE} is not active"
sudo systemctl is-active --quiet "${WORKER_SERVICE}" || fail "${WORKER_SERVICE} is not active"

log "Waiting for worker heartbeat"
heartbeat=false
for _ in $(seq 1 10); do
  if [[ -f "${MNT_WORKER_STATUS_FILE:-${DASHBOARD_DIR}/data/mnt_worker_status.json}" ]]; then
    heartbeat=true
    break
  fi
  sleep 1
done
[[ "${heartbeat}" == "true" ]] || {
  sudo systemctl status "${WORKER_SERVICE}" --no-pager || true
  fail "Alert worker started but did not write a heartbeat file"
}

log "Operational status"
"${VENV_DIR}/bin/python" mnt_status.py

log "Deployment complete"
printf 'Dashboard service: %s\n' "$(systemctl is-active "${DASHBOARD_SERVICE}" 2>/dev/null || true)"
printf 'Alert worker:      %s\n' "$(systemctl is-active "${WORKER_SERVICE}" 2>/dev/null || true)"
printf 'Dashboard URL:     http://127.0.0.1:8080\n'
printf 'Mode:              shadow/research; no brokerage order placement\n'
