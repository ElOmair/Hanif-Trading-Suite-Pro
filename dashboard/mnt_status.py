from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any

from shadow_trade_store import shadow_trade_summary
from worker_health import read_worker_status


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def operational_status(
    heartbeat: dict[str, Any] | None = None,
    *,
    now: datetime | None = None,
    stale_after_seconds: float | None = None,
) -> dict[str, Any]:
    heartbeat = heartbeat or read_worker_status()
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    stale_after = float(
        stale_after_seconds
        if stale_after_seconds is not None
        else os.getenv("MNT_WORKER_STALE_SECONDS", "180")
    )
    heartbeat_at = _parse_time(heartbeat.get("heartbeat_at"))
    age = (now - heartbeat_at).total_seconds() if heartbeat_at else None
    stale = age is None or age > max(30.0, stale_after)

    raw_state = str(heartbeat.get("worker_state") or "UNKNOWN").upper()
    if raw_state in {"NO_HEARTBEAT", "INVALID_HEARTBEAT", "ERROR"} or stale:
        overall = "ATTENTION"
    elif raw_state in {"DEGRADED", "PARTIAL"}:
        overall = "DEGRADED"
    elif raw_state in {"HEALTHY", "OFF_HOURS"}:
        overall = "OK"
    else:
        overall = "UNKNOWN"

    return {
        "overall": overall,
        "worker_state": raw_state,
        "heartbeat_age_seconds": round(age, 1) if age is not None else None,
        "heartbeat_stale": stale,
        "market_scan_active": heartbeat.get("market_scan_active"),
        "radar": heartbeat.get("radar") or {},
        "fusion": heartbeat.get("fusion") or {},
        "alerts": heartbeat.get("alerts") or {},
        "shadow_last_scan": heartbeat.get("shadow") or {},
        "loop_error": heartbeat.get("loop_error"),
        "status_file": heartbeat.get("status_file"),
    }


def build_report() -> dict[str, Any]:
    return {
        "operations": operational_status(),
        "ready_alert_shadow_results": shadow_trade_summary(limit=1000),
        "mode": "research/shadow; no brokerage order authorization",
    }


def main() -> None:
    report = build_report()
    print(json.dumps(report, indent=2, sort_keys=True))
    raise SystemExit(0 if report["operations"]["overall"] in {"OK", "DEGRADED"} else 1)


if __name__ == "__main__":
    main()
