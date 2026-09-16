from __future__ import annotations

from typing import Any, Iterable

from mnt_engine import clamp, score_position_bars


def _number(value: Any, default: float | None = None) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed == parsed else default


def _simple_why(score: float) -> str:
    if score >= 82:
        return "The stock has a strong multi-week uptrend and has held above important longer-term averages."
    if score >= 72:
        return "The larger trend is healthy, but MnT would rather see a good entry than chase a fast move."
    if score >= 64:
        return "The stock has some positive longer-term signs, but the setup is not strong enough to rush into."
    return "The longer-term price trend is mixed, so patience matters."


def build_position_profile(
    symbol: str,
    bars: Iterable[dict[str, Any]],
    *,
    intraday_score: float | None = None,
) -> dict[str, Any] | None:
    """Build one authoritative MnT daily/swing profile.

    The same profile can drive the Swing and 3–4 Month Hold lanes. Keeping this
    math server-side makes it testable and prevents the browser from inventing a
    different score than later backtests or alerts.
    """
    profile = score_position_bars(bars)
    if profile is None:
        return None

    position_score = float(profile["score"])
    fast_score = _number(intraday_score)
    swing_score = position_score
    if fast_score is not None:
        swing_score = clamp(position_score * 0.68 + fast_score * 0.32, 0.0, 100.0)

    ret60 = float(profile.get("ret60_pct") or 0.0)
    trend = str(profile.get("trend") or "WEAK").upper()
    hold_eligible = position_score >= 68.0 and ret60 > -4.0
    swing_eligible = swing_score >= 66.0

    return {
        "symbol": symbol.strip().upper(),
        **profile,
        "swing_score": round(swing_score, 1),
        "swing_eligible": swing_eligible,
        "hold_eligible": hold_eligible,
        "best_fit": (
            "3-4_MONTH_SHARES"
            if hold_eligible and position_score >= 82.0
            else "SWING_SHARES_OR_30_60D_OPTION_WATCH"
            if swing_eligible
            else "WATCHLIST"
        ),
        "simple_why": _simple_why(position_score),
        "trend_quality": "HEALTHY" if trend == "UPTREND" else "MIXED" if trend == "IMPROVING" else "WEAK",
        "research_only": True,
        "score_source": "mnt_engine.score_position_bars",
    }


def rank_opportunities(
    candidates: Iterable[dict[str, Any]],
    *,
    lane: str,
    limit: int = 4,
) -> list[dict[str, Any]]:
    """Rank already-built profiles for one Opportunity Desk lane."""
    lane = lane.strip().lower()
    rows = [dict(row) for row in candidates if row]
    limit = max(1, min(50, int(limit)))

    if lane == "swing":
        rows = [row for row in rows if row.get("swing_eligible")]
        rows.sort(key=lambda row: float(row.get("swing_score") or 0.0), reverse=True)
    elif lane in {"hold", "position", "3-4_month"}:
        rows = [row for row in rows if row.get("hold_eligible")]
        rows.sort(key=lambda row: float(row.get("score") or 0.0), reverse=True)
    else:
        raise ValueError(f"Unsupported opportunity lane: {lane}")

    return rows[:limit]
