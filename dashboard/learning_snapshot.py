from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from calibration_report import build_report

ROOT = Path(__file__).resolve().parent
DEFAULT_RUNTIME_PATH = ROOT / "static" / "mnt-runtime.json"


def runtime_path() -> Path:
    return Path(os.getenv("MNT_RUNTIME_SNAPSHOT_FILE", str(DEFAULT_RUNTIME_PATH))).expanduser()


def _public_worker_status(status: dict[str, Any] | None) -> dict[str, Any]:
    status = status or {}
    return {
        "worker_state": status.get("worker_state"),
        "market_scan_active": status.get("market_scan_active"),
        "heartbeat_at": status.get("heartbeat_at"),
        "session_risk": status.get("session_risk") or {},
        "radar": {
            "used": (status.get("radar") or {}).get("used"),
            "stale": (status.get("radar") or {}).get("stale"),
            "shortlist": (status.get("radar") or {}).get("shortlist") or [],
        },
        "fusion": status.get("fusion") or {},
        "alerts": status.get("alerts") or {},
        "shadow": status.get("shadow") or {},
    }


def build_learning_snapshot(worker_status: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build browser-safe learning metrics.

    No environment values, credentials, raw alert payloads, or brokerage data are
    written to this file. It contains only aggregate shadow/calibration metrics
    and the operational heartbeat already intended for local status display.
    """
    report = build_report(limit=2000)
    summary = report.get("summary") or {}
    shadow = report.get("ready_alert_shadow_trades") or {}
    options = report.get("option_contract_shadow_returns") or {}
    policy = report.get("policy") or {}
    layers = report.get("layer_effectiveness") or {}

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "shadow/research",
        "worker": _public_worker_status(worker_status),
        "learning": {
            "signal_calibration": {
                "total": summary.get("total"),
                "resolved": summary.get("resolved"),
                "wins": summary.get("wins"),
                "losses": summary.get("losses"),
                "ambiguous": summary.get("ambiguous"),
                "pending": summary.get("pending"),
                "target_first_win_rate_pct": summary.get("target_first_win_rate_pct"),
            },
            "ready_alerts": shadow,
            "option_contract_returns": options,
            "threshold_policy": {
                "status": policy.get("status"),
                "current_min_score": policy.get("current_min_score"),
                "recommended_min_score": policy.get("recommended_min_score"),
                "resolved_samples": policy.get("resolved_samples"),
                "minimum_samples_required": policy.get("minimum_samples_required"),
                "target_win_rate_pct": policy.get("target_win_rate_pct"),
                "reason": policy.get("reason"),
            },
            "layer_effectiveness": layers,
        },
        "beginner_explanation": (
            "This page shows how MnT's shadow ideas are actually behaving. Small samples are learning data, not proof that a setup will keep working."
        ),
        "research_only": True,
    }


def write_learning_snapshot(
    worker_status: dict[str, Any] | None = None,
    path: Path | None = None,
) -> Path:
    path = path or runtime_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = build_learning_snapshot(worker_status)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    temp.replace(path)
    return path
