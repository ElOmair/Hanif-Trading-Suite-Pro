from __future__ import annotations

import argparse
import json
import statistics
from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from option_shadow_store import list_option_marks, mark_timing_error_minutes
from shadow_trade_store import list_shadow_trades
from signal_store import get_signal

ET = ZoneInfo("America/New_York")


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


def _number(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed == parsed else None


def _session_date(value: str | date | None, now: datetime | None = None) -> date:
    if isinstance(value, date):
        return value
    if value:
        return date.fromisoformat(str(value))
    now = (now or datetime.now(timezone.utc)).astimezone(ET)
    return now.date()


def _horizon_eligible_trade(
    trade: dict[str, Any],
    *,
    horizon_minutes: int,
    max_timing_error_minutes: float,
) -> bool:
    created = _parse_time(trade.get("created_at"))
    option_symbol = str(trade.get("option_symbol") or "").strip()
    entry_ask = _number(trade.get("option_ask"))
    if created is None or not option_symbol or entry_ask is None or entry_ask <= 0:
        return False
    created_et = created.astimezone(ET)
    # Regular options quotes end at the normal session close. A source quote can
    # still be accepted when its timestamp is within the configured timing error
    # of the nominal horizon, so allow target times through close + tolerance.
    close_et = datetime.combine(created_et.date(), time(16, 0), tzinfo=ET)
    target_et = created_et + timedelta(minutes=int(horizon_minutes))
    latest_acceptable_target = close_et + timedelta(minutes=float(max_timing_error_minutes))
    return target_et <= latest_acceptable_target


def build_daily_scorecard(
    session_date: str | date | None = None,
    *,
    now: datetime | None = None,
    option_horizon_minutes: int = 60,
    max_mark_lag_minutes: float = 10.0,
    trades: list[dict[str, Any]] | None = None,
    marks: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    target_date = _session_date(session_date, now)
    all_trades = trades if trades is not None else list_shadow_trades(limit=5000)
    all_marks = marks if marks is not None else list_option_marks(limit=20000)

    day_trades: list[dict[str, Any]] = []
    trade_ids: set[int] = set()
    for trade in all_trades:
        created = _parse_time(trade.get("created_at"))
        if created is None or created.astimezone(ET).date() != target_date:
            continue
        day_trades.append(trade)
        if trade.get("id") is not None:
            trade_ids.add(int(trade["id"]))

    eligible_trade_ids = {
        int(trade["id"])
        for trade in day_trades
        if trade.get("id") is not None
        and _horizon_eligible_trade(
            trade,
            horizon_minutes=option_horizon_minutes,
            max_timing_error_minutes=max_mark_lag_minutes,
        )
    }

    day_marks = []
    for mark in all_marks:
        trade_id = int(mark.get("shadow_trade_id") or -1)
        if trade_id not in trade_ids:
            continue
        if int(mark.get("horizon_minutes") or 0) != int(option_horizon_minutes):
            continue
        timing_error = mark_timing_error_minutes(mark)
        result = _number(mark.get("return_bid_vs_entry_ask_pct"))
        if timing_error is None or result is None or timing_error > float(max_mark_lag_minutes):
            continue
        day_marks.append(mark)

    measured_trade_ids = {int(mark.get("shadow_trade_id") or -1) for mark in day_marks}
    eligible_count = len(eligible_trade_ids)
    measured_count = len(eligible_trade_ids & measured_trade_ids)
    missing_eligible = max(0, eligible_count - measured_count)
    completeness_pct = 100.0 * measured_count / eligible_count if eligible_count else None

    returns = [float(mark["return_bid_vs_entry_ask_pct"]) for mark in day_marks]
    positive = sum(1 for value in returns if value > 0)
    avg_return = sum(returns) / len(returns) if returns else None
    median_return = statistics.median(returns) if returns else None

    trade_by_id = {int(trade["id"]): trade for trade in day_trades if trade.get("id") is not None}
    best = max(day_marks, key=lambda row: float(row["return_bid_vs_entry_ask_pct"]), default=None)
    worst = min(day_marks, key=lambda row: float(row["return_bid_vs_entry_ask_pct"]), default=None)

    def mark_card(mark: dict[str, Any] | None) -> dict[str, Any] | None:
        if not mark:
            return None
        trade = trade_by_id.get(int(mark.get("shadow_trade_id") or -1)) or {}
        return {
            "underlying": trade.get("symbol"),
            "direction": trade.get("direction"),
            "option_symbol": mark.get("option_symbol") or trade.get("option_symbol"),
            "return_pct": round(float(mark["return_bid_vs_entry_ask_pct"]), 2),
            "fusion_score": trade.get("fusion_score"),
            "coverage_pct": trade.get("coverage_pct"),
            "timing_error_minutes": mark_timing_error_minutes(mark),
        }

    wins = losses = ambiguous = pending = 0
    for trade in day_trades:
        signal_id = trade.get("signal_id")
        signal = get_signal(int(signal_id)) if signal_id is not None else None
        label = str((((signal or {}).get("outcome") or {}).get("calibration_label") or "")).upper()
        if label == "WIN":
            wins += 1
        elif label == "LOSS":
            losses += 1
        elif label == "AMBIGUOUS":
            ambiguous += 1
        else:
            pending += 1

    resolved = wins + losses
    positive_rate = 100.0 * positive / len(returns) if returns else None
    if len(returns) < 3:
        quality = "COLLECTING"
        next_session = "Not enough measured option outcomes yet to change behavior. Keep collecting shadow evidence."
    elif positive_rate is not None and positive_rate >= 60.0 and avg_return is not None and avg_return > 0:
        quality = "STRONG"
        next_session = "Shadow option performance was constructive. Keep the same gates; do not loosen them from one strong day."
    elif (positive_rate is not None and positive_rate < 40.0) or (avg_return is not None and avg_return <= -15.0):
        quality = "WEAK"
        next_session = "Shadow option performance was poor. Favor patience and let calibration/holdout evidence determine whether thresholds should tighten."
    else:
        quality = "MIXED"
        next_session = "Results were mixed. Keep current gates and wait for more resolved evidence before changing thresholds or weights."

    longs = sum(1 for trade in day_trades if str(trade.get("direction") or "").upper() == "LONG")
    shorts = sum(1 for trade in day_trades if str(trade.get("direction") or "").upper() == "SHORT")
    delivered = sum(1 for trade in day_trades if bool(trade.get("discord_sent")))

    return {
        "session_date_et": target_date.isoformat(),
        "quality_state": quality,
        "ready_ideas": len(day_trades),
        "discord_delivered": delivered,
        "long_ideas": longs,
        "short_ideas": shorts,
        "underlying_outcomes": {
            "resolved": resolved,
            "wins": wins,
            "losses": losses,
            "ambiguous": ambiguous,
            "pending": pending,
            "target_first_win_rate_pct": round(100.0 * wins / resolved, 1) if resolved else None,
        },
        "option_horizon_minutes": int(option_horizon_minutes),
        "max_timing_error_minutes": float(max_mark_lag_minutes),
        "option_evidence": {
            "eligible_trades": eligible_count,
            "measured_trades": measured_count,
            "missing_eligible_trades": missing_eligible,
            "completeness_pct": round(completeness_pct, 1) if completeness_pct is not None else None,
            "complete": missing_eligible == 0,
        },
        "option_marks": {
            "count": len(returns),
            "positive_count": positive,
            "positive_rate_pct": round(positive_rate, 1) if positive_rate is not None else None,
            "average_return_pct": round(avg_return, 2) if avg_return is not None else None,
            "median_return_pct": round(float(median_return), 2) if median_return is not None else None,
            "gain_20pct_or_more": sum(1 for value in returns if value >= 20.0),
            "gain_50pct_or_more": sum(1 for value in returns if value >= 50.0),
            "loss_25pct_or_worse": sum(1 for value in returns if value <= -25.0),
            "loss_50pct_or_worse": sum(1 for value in returns if value <= -50.0),
        },
        "best_option": mark_card(best),
        "worst_option": mark_card(worst),
        "next_session_note": next_session,
        "return_convention": "entry at surfaced ask; later mark at bid",
        "timing_convention": "source quote timestamp preferred; collector lag used only for legacy marks",
        "research_only": True,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Print one MnT shadow-session scorecard.")
    parser.add_argument("--date", help="ET session date in YYYY-MM-DD; defaults to today")
    parser.add_argument("--horizon", type=int, default=60, help="Option mark horizon in minutes")
    parser.add_argument("--max-lag", type=float, default=10.0, help="Ignore marks whose source quote timing differs from the horizon by more than this many minutes")
    args = parser.parse_args()
    print(
        json.dumps(
            build_daily_scorecard(args.date, option_horizon_minutes=max(1, args.horizon), max_mark_lag_minutes=max(0.0, args.max_lag)),
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
