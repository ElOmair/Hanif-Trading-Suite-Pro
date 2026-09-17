from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from calibration_report import build_report
from daily_scorecard import build_daily_scorecard

ROOT = Path(__file__).resolve().parent
DEFAULT_RUNTIME_PATH = ROOT / "static" / "mnt-runtime.json"


def runtime_path() -> Path:
    return Path(os.getenv("MNT_RUNTIME_SNAPSHOT_FILE", str(DEFAULT_RUNTIME_PATH))).expanduser()


def _env_int(name: str, default: int, minimum: int = 0) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(minimum, value)


def _env_float(name: str, default: float, minimum: float = 0.0) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(minimum, value)


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


def _aggregate_signal_calibration(summary: dict[str, Any]) -> dict[str, Any]:
    buckets = summary.get("score_buckets") or {}
    wins = losses = ambiguous = unresolved = 0
    for raw in buckets.values():
        bucket = raw or {}
        wins += int(bucket.get("wins") or 0)
        losses += int(bucket.get("losses") or 0)
        ambiguous += int(bucket.get("ambiguous") or 0)
        unresolved += int(bucket.get("unresolved") or 0)
    resolved = wins + losses
    evaluated = int(summary.get("evaluated_count") or 0)
    total = int(summary.get("total_count") or 0)
    return {
        "total": total,
        "evaluated": evaluated,
        "resolved": resolved,
        "wins": wins,
        "losses": losses,
        "ambiguous": ambiguous,
        "unresolved": unresolved,
        "pending": max(0, total - evaluated),
        "target_first_win_rate_pct": round(100.0 * wins / resolved, 1) if resolved else None,
    }


def _public_weight_challenge(challenge: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": challenge.get("status"),
        "resolved": challenge.get("resolved"),
        "training_count": challenge.get("training_count"),
        "holdout_count": challenge.get("holdout_count"),
        "recommend_candidate": bool(challenge.get("recommend_candidate")),
        "holdout_improvement_pct_points": challenge.get("holdout_improvement_pct_points"),
        "minimum_improvement_pct_points": challenge.get("minimum_improvement_pct_points"),
        "baseline_holdout": challenge.get("baseline_holdout") or {},
        "candidate_holdout": challenge.get("candidate_holdout") or {},
        "proposed_changes": challenge.get("proposed_changes") or [],
        "current_weights": challenge.get("current_weights") or {},
        "candidate_weights": challenge.get("candidate_weights") or {},
        "reason": challenge.get("reason"),
        "research_only": True,
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
    challenge = report.get("weight_challenge") or {}
    current = policy.get("current") or {}
    recommended = policy.get("recommended") or {}
    scorecard = build_daily_scorecard(
        option_horizon_minutes=_env_int("MNT_DAILY_SCORECARD_OPTION_HORIZON", 60, 1),
        max_mark_lag_minutes=_env_float("MNT_OPTION_MARK_MAX_LAG_MINUTES", 10.0, 0.0),
    )

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "shadow/research",
        "worker": _public_worker_status(worker_status),
        "learning": {
            "signal_calibration": _aggregate_signal_calibration(summary),
            "ready_alerts": shadow,
            "option_contract_returns": options,
            "daily_scorecard": scorecard,
            "threshold_policy": {
                "status": policy.get("status"),
                "current_min_score": current.get("min_score"),
                "current_min_coverage_pct": current.get("min_coverage_pct"),
                "recommended_min_score": recommended.get("min_score"),
                "recommended_min_coverage_pct": recommended.get("min_coverage_pct"),
                "resolved_samples": policy.get("resolved_count"),
                "minimum_samples_required": policy.get("minimum_resolved_samples"),
                "target_win_rate_pct": policy.get("target_win_rate_pct"),
                "score_delta": policy.get("score_delta"),
                "reason": policy.get("reason"),
            },
            "layer_effectiveness": layers,
            "weight_challenge": _public_weight_challenge(challenge),
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
