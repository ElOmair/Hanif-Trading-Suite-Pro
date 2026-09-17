from __future__ import annotations

from math import sqrt
from typing import Any, Iterable


def _number(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed == parsed else None


def _label(row: dict[str, Any]) -> int | None:
    value = str(((row.get("outcome") or {}).get("calibration_label") or "")).upper()
    if value == "WIN":
        return 1
    if value == "LOSS":
        return 0
    return None


def _score(row: dict[str, Any]) -> float | None:
    direct = _number(row.get("score"))
    if direct is not None:
        return direct
    payload = row.get("payload") or {}
    fusion = payload.get("fusion_score") or {}
    return _number(fusion.get("score"))


def _wilson_interval(successes: int, total: int, z: float = 1.96) -> tuple[float | None, float | None]:
    if total <= 0:
        return None, None
    p = successes / total
    denominator = 1.0 + z * z / total
    center = (p + z * z / (2.0 * total)) / denominator
    margin = z * sqrt((p * (1.0 - p) + z * z / (4.0 * total)) / total) / denominator
    return max(0.0, center - margin), min(1.0, center + margin)


def _auc(pairs: list[tuple[float, int]]) -> float | None:
    """Mann-Whitney ROC AUC with 0.5 credit for tied scores."""
    wins = [score for score, label in pairs if label == 1]
    losses = [score for score, label in pairs if label == 0]
    if not wins or not losses:
        return None
    favorable = 0.0
    for win_score in wins:
        for loss_score in losses:
            if win_score > loss_score:
                favorable += 1.0
            elif win_score == loss_score:
                favorable += 0.5
    return favorable / (len(wins) * len(losses))


def _band(rows: list[tuple[float, int]]) -> dict[str, Any]:
    total = len(rows)
    wins = sum(label for _, label in rows)
    low, high = _wilson_interval(wins, total)
    return {
        "count": total,
        "wins": wins,
        "losses": total - wins,
        "win_rate_pct": round(100.0 * wins / total, 1) if total else None,
        "wilson_95_low_pct": round(100.0 * low, 1) if low is not None else None,
        "wilson_95_high_pct": round(100.0 * high, 1) if high is not None else None,
        "average_score": round(sum(score for score, _ in rows) / total, 1) if total else None,
    }


def summarize_score_discrimination(
    rows: Iterable[dict[str, Any]],
    *,
    minimum_resolved: int = 30,
    band_fraction: float = 0.25,
) -> dict[str, Any]:
    pairs: list[tuple[float, int]] = []
    for row in rows:
        label = _label(row)
        score = _score(row)
        if label is None or score is None:
            continue
        pairs.append((float(score), int(label)))
    pairs.sort(key=lambda item: item[0])

    count = len(pairs)
    auc = _auc(pairs)
    band_size = max(1, int(round(count * max(0.10, min(0.40, float(band_fraction)))))) if count else 0
    bottom = pairs[:band_size] if band_size else []
    top = pairs[-band_size:] if band_size else []
    top_band = _band(top)
    bottom_band = _band(bottom)
    top_rate = _number(top_band.get("win_rate_pct"))
    bottom_rate = _number(bottom_band.get("win_rate_pct"))
    separation = top_rate - bottom_rate if top_rate is not None and bottom_rate is not None else None

    if count < int(minimum_resolved):
        state = "COLLECTING"
        reason = f"Need at least {int(minimum_resolved)} resolved WIN/LOSS signals before judging score discrimination."
    elif auc is None:
        state = "INSUFFICIENT_CLASSES"
        reason = "Resolved history does not yet contain both wins and losses."
    elif auc >= 0.70 and separation is not None and separation >= 20.0:
        state = "STRONG"
        reason = "Higher Fusion scores are materially ranking wins above losses in the resolved shadow sample."
    elif auc >= 0.60 and separation is not None and separation >= 10.0:
        state = "USEFUL"
        reason = "Fusion score has positive ranking power, but more evidence is needed before treating the numeric score as highly reliable."
    elif auc >= 0.52:
        state = "WEAK"
        reason = "Fusion score is only weakly separating wins from losses; avoid aggressive threshold tuning from the current sample."
    else:
        state = "NOT_SEPARATING"
        reason = "Higher Fusion scores are not currently ranking resolved wins above losses reliably."

    wins = sum(label for _, label in pairs)
    overall_low, overall_high = _wilson_interval(wins, count)
    return {
        "state": state,
        "resolved": count,
        "minimum_resolved": int(minimum_resolved),
        "wins": wins,
        "losses": count - wins,
        "overall_win_rate_pct": round(100.0 * wins / count, 1) if count else None,
        "overall_wilson_95_low_pct": round(100.0 * overall_low, 1) if overall_low is not None else None,
        "overall_wilson_95_high_pct": round(100.0 * overall_high, 1) if overall_high is not None else None,
        "roc_auc": round(auc, 3) if auc is not None else None,
        "band_fraction": float(band_fraction),
        "top_score_band": top_band,
        "bottom_score_band": bottom_band,
        "top_minus_bottom_win_rate_pct_points": round(separation, 1) if separation is not None else None,
        "reason": reason,
        "research_only": True,
        "note": "AUC measures ranking discrimination, not the probability calibration of the 0-100 Fusion score.",
    }
