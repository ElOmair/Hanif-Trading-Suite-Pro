from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
DEFAULT_STATUS_PATH = ROOT / "data" / "mnt_worker_status.json"


def status_path() -> Path:
    return Path(os.getenv("MNT_WORKER_STATUS_FILE", str(DEFAULT_STATUS_PATH))).expanduser()


def _classification_state(item: dict[str, Any]) -> str:
    classification = item.get("classification") or {}
    return str(classification.get("state") or "").upper()


def build_worker_status(
    results: list[dict[str, Any]] | None,
    *,
    market_active: bool,
    scan_started_at: str | None = None,
    scan_finished_at: str | None = None,
    loop_error: str | None = None,
) -> dict[str, Any]:
    results = results or []
    radar = next((item for item in results if item.get("stage") == "radar"), {})
    symbol_rows = [item for item in results if item.get("symbol")]

    fusion_ok = sum(1 for item in symbol_rows if not item.get("error"))
    fusion_errors = sum(1 for item in symbol_rows if item.get("error"))
    pretriggers = sum(1 for item in symbol_rows if _classification_state(item) == "PRE_TRIGGER")
    ready = sum(1 for item in symbol_rows if _classification_state(item) == "READY")
    stand_downs = sum(1 for item in symbol_rows if item.get("stand_down_sent"))
    discord_sent = sum(1 for item in symbol_rows if item.get("sent"))
    shadow_recorded = sum(1 for item in symbol_rows if item.get("shadow_trade_id") is not None)
    suppressed = sum(1 for item in symbol_rows if item.get("suppressed_by_rank"))

    now = datetime.now(timezone.utc).isoformat()
    if loop_error:
        state = "ERROR"
    elif not market_active:
        state = "OFF_HOURS"
    elif fusion_errors and not fusion_ok:
        state = "DEGRADED"
    elif fusion_errors:
        state = "PARTIAL"
    else:
        state = "HEALTHY"

    return {
        "worker_state": state,
        "market_scan_active": bool(market_active),
        "heartbeat_at": now,
        "scan_started_at": scan_started_at,
        "scan_finished_at": scan_finished_at or now,
        "radar": {
            "used": radar.get("used"),
            "cached": radar.get("cached"),
            "stale": radar.get("stale"),
            "error": radar.get("error"),
            "shortlist": radar.get("shortlist") or [],
            "sticky_pretriggers": radar.get("sticky_pretriggers") or [],
        },
        "fusion": {
            "attempted": len(symbol_rows),
            "successful": fusion_ok,
            "errors": fusion_errors,
        },
        "alerts": {
            "pretrigger_candidates": pretriggers,
            "ready_candidates": ready,
            "discord_sent": discord_sent,
            "stand_down_sent": stand_downs,
            "suppressed_by_rank": suppressed,
        },
        "shadow": {"ready_records_written": shadow_recorded},
        "loop_error": loop_error,
        "note": "Operational heartbeat only. No credentials, orders, or brokerage authorization are stored here.",
    }


def write_worker_status(status: dict[str, Any], path: Path | None = None) -> Path:
    path = path or status_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(status, indent=2, sort_keys=True), encoding="utf-8")
    temp.replace(path)
    return path


def read_worker_status(path: Path | None = None) -> dict[str, Any]:
    path = path or status_path()
    if not path.exists():
        return {
            "worker_state": "NO_HEARTBEAT",
            "status_file": str(path),
            "note": "The alert worker has not written a heartbeat yet.",
        }
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("status root is not an object")
        payload["status_file"] = str(path)
        return payload
    except Exception as exc:
        return {
            "worker_state": "INVALID_HEARTBEAT",
            "status_file": str(path),
            "error": type(exc).__name__,
        }
