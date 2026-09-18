from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Iterable
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")


def _label(row: dict[str, Any]) -> str | None:
    label = str(((row.get("outcome") or {}).get("calibration_label") or "")).upper()
    return label if label in {"WIN", "LOSS"} else None


def _created_at_et(row: dict[str, Any]) -> datetime | None:
    raw = row.get("created_at")
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(ET)
    except (TypeError, ValueError):
        return None


def _session_segment(row: dict[str, Any]) -> str:
    stamp = _created_at_et(row)
    if stamp is None:
        return "UNKNOWN"
    minute = stamp.hour * 60 + stamp.minute
    if 9 * 60 + 30 <= minute < 11 * 60:
        return "OPEN"
    if 11 * 60 <= minute < 14 * 60:
        return "MIDDAY"
    if 14 * 60 <= minute <= 16 * 60 + 5:
        return "AFTERNOON"
    return "OFF_HOURS"


def _bucket_score(row: dict[str, Any]) -> str:
    try:
        score = float(row.get("score"))
    except (TypeError, ValueError):
        return "UNKNOWN"
    low = int(score // 10) * 10
    high = low + 9
    return f"{low}-{high}"


def _slice_row(dimension: str, value: str, wins: int, losses: int, baseline: float | None, minimum: int) -> dict[str, Any]:
    resolved = wins + losses
    win_rate = 100.0 * wins / resolved if resolved else None
    lift = win_rate - baseline if win_rate is not None and baseline is not None else None
    if resolved < minimum:
        state = "INSUFFICIENT"
    elif lift is not None and lift >= 10.0:
        state = "SUPPORTED"
    elif lift is not None and lift <= -10.0:
        state = "CAUTION"
    else:
        state = "NEUTRAL"
    return {
        "dimension": dimension,
        "value": value,
        "resolved": resolved,
        "wins": wins,
        "losses": losses,
        "win_rate_pct": round(win_rate, 1) if win_rate is not None else None,
        "lift_vs_all_pct_points": round(lift, 1) if lift is not None else None,
        "state": state,
        "minimum_samples": minimum,
    }


def summarize_edge_slices(rows: Iterable[dict[str, Any]], *, min_samples: int = 8) -> dict[str, Any]:
    resolved_rows = [row for row in rows if _label(row) is not None]
    total_wins = sum(1 for row in resolved_rows if _label(row) == "WIN")
    total_losses = len(resolved_rows) - total_wins
    baseline = 100.0 * total_wins / len(resolved_rows) if resolved_rows else None

    groups: dict[tuple[str, str], dict[str, int]] = defaultdict(lambda: {"WIN": 0, "LOSS": 0})
    for row in resolved_rows:
        label = _label(row)
        symbol = str(row.get("symbol") or "UNKNOWN").upper()
        direction = str(row.get("direction") or "UNKNOWN").upper()
        segment = _session_segment(row)
        score_bucket = _bucket_score(row)
        for dimension, value in (
            ("symbol", symbol),
            ("direction", direction),
            ("session", segment),
            ("score_bucket", score_bucket),
        ):
            groups[(dimension, value)][label] += 1

    slices = [
        _slice_row(dimension, value, counts["WIN"], counts["LOSS"], baseline, max(1, int(min_samples)))
        for (dimension, value), counts in groups.items()
    ]
    slices.sort(key=lambda item: (item["dimension"], -(item["resolved"] or 0), item["value"]))
    eligible = [item for item in slices if item["resolved"] >= max(1, int(min_samples)) and item["lift_vs_all_pct_points"] is not None]
    best = sorted(eligible, key=lambda item: (item["lift_vs_all_pct_points"], item["resolved"]), reverse=True)[:5]
    worst = sorted(eligible, key=lambda item: (item["lift_vs_all_pct_points"], -item["resolved"]))[:5]

    by_dimension: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in slices:
        by_dimension[item["dimension"]].append(item)

    return {
        "resolved": len(resolved_rows),
        "baseline_win_rate_pct": round(baseline, 1) if baseline is not None else None,
        "minimum_samples_per_slice": max(1, int(min_samples)),
        "by_dimension": dict(by_dimension),
        "best_supported_slices": best,
        "weakest_supported_slices": worst,
        "note": "Slice statistics are descriptive. MnT does not auto-block symbols, directions, or times from this report.",
        "research_only": True,
    }
