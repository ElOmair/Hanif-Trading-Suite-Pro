from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

from layer_calibration import summarize_layer_effectiveness
from mnt_engine import LAYER_WEIGHTS


def _number(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed == parsed else None


def _label(row: dict[str, Any]) -> str | None:
    label = str(((row.get("outcome") or {}).get("calibration_label") or "")).upper()
    return label if label in {"WIN", "LOSS"} else None


def _created_at(row: dict[str, Any]) -> datetime:
    raw = row.get("created_at")
    try:
        parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return datetime.min.replace(tzinfo=timezone.utc)


def _components(row: dict[str, Any]) -> dict[str, Any]:
    payload = row.get("payload") or {}
    fusion = payload.get("fusion_score") or {}
    value = fusion.get("components") or {}
    return value if isinstance(value, dict) else {}


def score_with_weights(row: dict[str, Any], weights: Mapping[str, float]) -> tuple[float | None, float]:
    components = _components(row)
    total_weight = sum(max(0.0, float(value)) for value in weights.values())
    available_weight = 0.0
    weighted = 0.0
    for name, weight_raw in weights.items():
        weight = max(0.0, float(weight_raw))
        component = components.get(name)
        score = _number(component.get("score")) if isinstance(component, dict) else None
        if score is None:
            continue
        available_weight += weight
        weighted += score * weight
    if total_weight <= 0 or available_weight <= 0:
        return None, 0.0
    return weighted / available_weight, 100.0 * available_weight / total_weight


def _normalize_weights(weights: Mapping[str, float], total: float = 100.0) -> dict[str, float]:
    cleaned = {name: max(1.0, float(value)) for name, value in weights.items()}
    raw_total = sum(cleaned.values())
    if raw_total <= 0:
        return dict(LAYER_WEIGHTS)
    normalized = {name: round(value * total / raw_total, 3) for name, value in cleaned.items()}
    # Keep the sum exactly stable after rounding by assigning any residual to the largest layer.
    residual = round(total - sum(normalized.values()), 3)
    if normalized and residual:
        largest = max(normalized, key=normalized.get)
        normalized[largest] = round(normalized[largest] + residual, 3)
    return normalized


def build_candidate_weights(
    training_rows: Iterable[dict[str, Any]],
    *,
    current_weights: Mapping[str, float] | None = None,
    min_layer_lift_pct_points: float = 8.0,
    max_delta_weight: float = 2.5,
    supportive_score: float = 60.0,
    min_samples_per_side: int = 10,
) -> dict[str, Any]:
    current = dict(current_weights or LAYER_WEIGHTS)
    attribution = summarize_layer_effectiveness(
        training_rows,
        supportive_score=supportive_score,
        min_samples=min_samples_per_side,
    )
    candidate = dict(current)
    changes: list[dict[str, Any]] = []
    for item in attribution.get("review_priority") or []:
        name = str(item.get("layer") or "")
        lift = _number(item.get("lift_pct_points"))
        if name not in candidate or lift is None or abs(lift) < float(min_layer_lift_pct_points):
            continue
        direction = 1.0 if lift > 0 else -1.0
        # Scale modestly with observed lift but cap the experiment to avoid a recent
        # streak causing a large model rewrite.
        magnitude = min(float(max_delta_weight), max(1.0, abs(lift) / 10.0))
        delta = round(direction * magnitude, 3)
        candidate[name] = max(1.0, candidate[name] + delta)
        changes.append(
            {
                "layer": name,
                "observed_lift_pct_points": round(lift, 1),
                "raw_weight_delta": delta,
                "reason": "supportive layer historically separated wins from losses" if delta > 0 else "supportive layer historically underperformed its weak-state observations",
            }
        )
    normalized = _normalize_weights(candidate, total=sum(float(v) for v in current.values()))
    return {
        "current_weights": current,
        "candidate_weights": normalized,
        "changes": changes,
        "training_layer_effectiveness": attribution,
    }


def evaluate_weights(
    rows: Iterable[dict[str, Any]],
    weights: Mapping[str, float],
    *,
    min_score: float = 62.0,
    min_coverage_pct: float = 55.0,
) -> dict[str, Any]:
    selected = wins = losses = 0
    scores: list[float] = []
    for row in rows:
        label = _label(row)
        if label is None:
            continue
        score, coverage = score_with_weights(row, weights)
        if score is None or coverage < float(min_coverage_pct) or score < float(min_score):
            continue
        selected += 1
        scores.append(score)
        if label == "WIN":
            wins += 1
        else:
            losses += 1
    return {
        "selected": selected,
        "wins": wins,
        "losses": losses,
        "win_rate_pct": round(100.0 * wins / selected, 1) if selected else None,
        "average_selected_score": round(sum(scores) / len(scores), 1) if scores else None,
    }


def walk_forward_weight_challenge(
    rows: Iterable[dict[str, Any]],
    *,
    current_weights: Mapping[str, float] | None = None,
    train_fraction: float = 0.70,
    min_resolved: int = 40,
    min_holdout: int = 12,
    min_candidate_selected: int = 8,
    min_score: float = 62.0,
    min_coverage_pct: float = 55.0,
    min_layer_lift_pct_points: float = 8.0,
    min_holdout_improvement_pct_points: float = 3.0,
) -> dict[str, Any]:
    resolved = [row for row in rows if _label(row) is not None]
    resolved.sort(key=_created_at)
    current = dict(current_weights or LAYER_WEIGHTS)
    if len(resolved) < int(min_resolved):
        return {
            "status": "COLLECTING",
            "resolved": len(resolved),
            "minimum_resolved": int(min_resolved),
            "current_weights": current,
            "candidate_weights": current,
            "recommend_candidate": False,
            "reason": "Not enough resolved shadow signals for a chronological train/holdout weight challenge.",
            "research_only": True,
        }

    split = int(len(resolved) * max(0.5, min(0.85, float(train_fraction))))
    split = min(max(1, split), len(resolved) - 1)
    training = resolved[:split]
    holdout = resolved[split:]
    if len(holdout) < int(min_holdout):
        return {
            "status": "COLLECTING",
            "resolved": len(resolved),
            "training_count": len(training),
            "holdout_count": len(holdout),
            "minimum_holdout": int(min_holdout),
            "current_weights": current,
            "candidate_weights": current,
            "recommend_candidate": False,
            "reason": "Not enough later unseen signals in the holdout window yet.",
            "research_only": True,
        }

    proposal = build_candidate_weights(
        training,
        current_weights=current,
        min_layer_lift_pct_points=min_layer_lift_pct_points,
    )
    candidate = proposal["candidate_weights"]
    baseline_eval = evaluate_weights(holdout, current, min_score=min_score, min_coverage_pct=min_coverage_pct)
    candidate_eval = evaluate_weights(holdout, candidate, min_score=min_score, min_coverage_pct=min_coverage_pct)

    base_rate = _number(baseline_eval.get("win_rate_pct"))
    candidate_rate = _number(candidate_eval.get("win_rate_pct"))
    improvement = candidate_rate - base_rate if base_rate is not None and candidate_rate is not None else None
    baseline_selected = int(baseline_eval.get("selected") or 0)
    candidate_selected = int(candidate_eval.get("selected") or 0)
    selection_floor = max(int(min_candidate_selected), int(baseline_selected * 0.70)) if baseline_selected else int(min_candidate_selected)
    recommend = bool(
        proposal.get("changes")
        and improvement is not None
        and improvement >= float(min_holdout_improvement_pct_points)
        and candidate_selected >= selection_floor
    )

    return {
        "status": "CANDIDATE_VALIDATED" if recommend else "KEEP_CURRENT",
        "resolved": len(resolved),
        "training_count": len(training),
        "holdout_count": len(holdout),
        "train_fraction": float(train_fraction),
        "current_weights": current,
        "candidate_weights": candidate,
        "proposed_changes": proposal.get("changes") or [],
        "baseline_holdout": baseline_eval,
        "candidate_holdout": candidate_eval,
        "holdout_improvement_pct_points": round(improvement, 1) if improvement is not None else None,
        "minimum_improvement_pct_points": float(min_holdout_improvement_pct_points),
        "minimum_candidate_selected": selection_floor,
        "recommend_candidate": recommend,
        "reason": (
            "The candidate improved win rate on later unseen signals without collapsing the number of qualifying setups."
            if recommend
            else "The challenger did not clear the holdout improvement/sample safeguards; keep the current Fusion weights."
        ),
        "research_only": True,
        "note": "This is chronological shadow validation only. It never changes LAYER_WEIGHTS automatically.",
    }
