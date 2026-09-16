from __future__ import annotations

from typing import Any


def _number(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed == parsed else None


def build_calibration_policy(
    summary: dict[str, Any] | None,
    *,
    current_min_score: float = 62.0,
    current_min_coverage: float = 55.0,
    min_resolved_samples: int = 30,
    target_win_rate_pct: float = 55.0,
) -> dict[str, Any]:
    """Recommend a score threshold from observed signal outcomes.

    This function is deliberately conservative. It only produces an actionable
    recommendation after enough resolved WIN/LOSS outcomes exist. Until then it
    remains in shadow mode and leaves the live risk-governor threshold alone.
    """
    summary = summary or {}
    buckets = summary.get("score_buckets") or {}
    evaluated_count = int(_number(summary.get("evaluated_count")) or 0)

    rows: list[dict[str, Any]] = []
    total_resolved = 0
    for label, raw in buckets.items():
        bucket = raw or {}
        wins = int(_number(bucket.get("wins")) or 0)
        losses = int(_number(bucket.get("losses")) or 0)
        resolved = wins + losses
        total_resolved += resolved
        try:
            lower = int(str(label).split("-", 1)[0])
        except (TypeError, ValueError):
            continue
        win_rate = 100.0 * wins / resolved if resolved else None
        rows.append(
            {
                "bucket": str(label),
                "lower_score": lower,
                "resolved": resolved,
                "wins": wins,
                "losses": losses,
                "win_rate_pct": round(win_rate, 1) if win_rate is not None else None,
            }
        )

    rows.sort(key=lambda item: item["lower_score"])
    enough_data = total_resolved >= max(1, int(min_resolved_samples))

    # For each possible threshold, aggregate all resolved samples at/above it.
    candidates: list[dict[str, Any]] = []
    for row in rows:
        threshold = row["lower_score"]
        eligible = [item for item in rows if item["lower_score"] >= threshold]
        wins = sum(int(item["wins"]) for item in eligible)
        losses = sum(int(item["losses"]) for item in eligible)
        resolved = wins + losses
        if not resolved:
            continue
        win_rate = 100.0 * wins / resolved
        candidates.append(
            {
                "threshold": float(threshold),
                "resolved": resolved,
                "wins": wins,
                "losses": losses,
                "win_rate_pct": round(win_rate, 1),
            }
        )

    eligible_candidates = [
        item
        for item in candidates
        if item["resolved"] >= max(10, min_resolved_samples // 2)
        and item["win_rate_pct"] >= target_win_rate_pct
    ]

    recommended_score = float(current_min_score)
    reason = "Not enough resolved signal history to change the live score threshold."
    status = "SHADOW_LEARNING"

    if enough_data and eligible_candidates:
        # Prefer the lowest threshold that still clears the target win rate so
        # the model does not overfit by selecting only a tiny number of trades.
        chosen = sorted(eligible_candidates, key=lambda item: (item["threshold"], -item["resolved"]))[0]
        recommended_score = max(float(current_min_score), float(chosen["threshold"]))
        status = "READY_FOR_REVIEW"
        reason = (
            f"Signals scoring at least {chosen['threshold']:.0f} produced a "
            f"{chosen['win_rate_pct']:.1f}% target-first win rate across "
            f"{chosen['resolved']} resolved samples."
        )
    elif enough_data:
        status = "KEEP_CURRENT"
        reason = (
            "Enough history exists to review, but no score threshold currently "
            "meets the configured win-rate and sample-size requirements."
        )

    delta = recommended_score - float(current_min_score)
    return {
        "status": status,
        "shadow_mode": True,
        "evaluated_count": evaluated_count,
        "resolved_count": total_resolved,
        "minimum_resolved_samples": int(min_resolved_samples),
        "target_win_rate_pct": float(target_win_rate_pct),
        "current": {
            "min_score": float(current_min_score),
            "min_coverage_pct": float(current_min_coverage),
        },
        "recommended": {
            "min_score": round(recommended_score, 1),
            "min_coverage_pct": float(current_min_coverage),
        },
        "score_delta": round(delta, 1),
        "reason": reason,
        "candidates": candidates,
        "note": (
            "Calibration is advisory only. MnT does not automatically change the "
            "live execution gate from historical results."
        ),
    }
