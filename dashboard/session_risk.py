from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from option_shadow_store import list_option_marks, mark_timing_error_minutes
from shadow_trade_store import list_shadow_trades

ET = ZoneInfo("America/New_York")


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int, minimum: int = 0) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(minimum, value)


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


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


def evaluate_session_risk(
    trades: list[dict[str, Any]],
    marks: list[dict[str, Any]],
    *,
    now: datetime | None = None,
    max_ready_alerts: int = 8,
    loss_horizon_minutes: int = 60,
    bad_option_return_pct: float = -25.0,
    max_consecutive_bad_marks: int = 3,
    max_mark_timing_error_minutes: float = 10.0,
    enforce: bool = False,
) -> dict[str, Any]:
    """Evaluate daily alert fatigue / loss-streak risk from shadow evidence.

    This governor is intentionally based on what MnT actually surfaced, not on
    brokerage P/L. It defaults to advisory mode and must be explicitly enabled
    before it can suppress new alert delivery. Option marks only influence the
    streak when their source quote timing is close enough to the requested horizon.
    """
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    today_et = now.astimezone(ET).date()

    today_trades = []
    today_trade_ids: set[int] = set()
    for trade in trades:
        created = _parse_time(trade.get("created_at"))
        if created is None or created.astimezone(ET).date() != today_et:
            continue
        today_trades.append(trade)
        if trade.get("id") is not None:
            today_trade_ids.add(int(trade["id"]))

    relevant_marks = []
    ignored_timing_marks = 0
    for mark in marks:
        if int(mark.get("horizon_minutes") or 0) != int(loss_horizon_minutes):
            continue
        if int(mark.get("shadow_trade_id") or -1) not in today_trade_ids:
            continue
        timing_error = mark_timing_error_minutes(mark)
        if timing_error is None or timing_error > float(max_mark_timing_error_minutes):
            ignored_timing_marks += 1
            continue
        value = mark.get("return_bid_vs_entry_ask_pct")
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            continue
        relevant_marks.append((int(mark.get("id") or 0), numeric))
    relevant_marks.sort(key=lambda item: item[0])

    consecutive_bad = 0
    for _, value in reversed(relevant_marks):
        if value <= float(bad_option_return_pct):
            consecutive_bad += 1
        else:
            break

    ready_limit_hit = len(today_trades) >= max(1, int(max_ready_alerts))
    loss_streak_hit = consecutive_bad >= max(1, int(max_consecutive_bad_marks))
    tripped = ready_limit_hit or loss_streak_hit

    reasons = []
    if ready_limit_hit:
        reasons.append(f"MnT has already surfaced {len(today_trades)} READY ideas today.")
    if loss_streak_hit:
        reasons.append(
            f"The last {consecutive_bad} measured {loss_horizon_minutes}-minute option marks were {abs(float(bad_option_return_pct)):.0f}% losses or worse."
        )

    return {
        "state": "PAUSE_NEW_ALERTS" if tripped else "NORMAL",
        "tripped": tripped,
        "enforced": bool(enforce),
        "entry_review_blocked": bool(enforce and tripped),
        "session_date_et": today_et.isoformat(),
        "ready_ideas_today": len(today_trades),
        "max_ready_alerts": int(max_ready_alerts),
        "loss_horizon_minutes": int(loss_horizon_minutes),
        "bad_option_return_pct": float(bad_option_return_pct),
        "eligible_option_marks": len(relevant_marks),
        "ignored_timing_marks": ignored_timing_marks,
        "max_mark_timing_error_minutes": float(max_mark_timing_error_minutes),
        "consecutive_bad_option_marks": consecutive_bad,
        "max_consecutive_bad_marks": int(max_consecutive_bad_marks),
        "reasons": reasons,
        "beginner_explanation": (
            "MnT is recommending a break from new setups because either too many trades have already appeared today or recent option results have been unusually poor."
            if tripped
            else "MnT's session-level safety limits are not currently being triggered."
        ),
        "note": "This is a shadow-alert risk governor, not brokerage account P/L.",
    }


def session_risk_status(now: datetime | None = None) -> dict[str, Any]:
    return evaluate_session_risk(
        list_shadow_trades(limit=1000),
        list_option_marks(limit=5000),
        now=now,
        max_ready_alerts=_env_int("MNT_SESSION_MAX_READY_ALERTS", 8, 1),
        loss_horizon_minutes=_env_int("MNT_SESSION_LOSS_HORIZON_MINUTES", 60, 1),
        bad_option_return_pct=_env_float("MNT_SESSION_BAD_OPTION_RETURN_PCT", -25.0),
        max_consecutive_bad_marks=_env_int("MNT_SESSION_MAX_CONSECUTIVE_BAD_MARKS", 3, 1),
        max_mark_timing_error_minutes=max(0.0, _env_float("MNT_SESSION_MAX_MARK_TIMING_ERROR_MINUTES", 10.0)),
        enforce=_env_bool("MNT_SESSION_RISK_ENFORCE", False),
    )
