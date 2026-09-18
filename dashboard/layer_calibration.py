from __future__ import annotations

from typing import Any, Iterable


def _number(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed == parsed else None


def _resolved_label(row: dict[str, Any]) -> str | None:
    outcome = row.get("outcome") or {}
    label = str(outcome.get("calibration_label") or "").upper()
    return label if label in {"WIN", "LOSS"} else None


def _rate(wins: int, losses: int) -> float | None:
    total = wins + losses
    return round(100.0 * wins / total, 1) if total else None


def summarize_layer_effectiveness(
    rows: Iterable[dict[str, Any]],
    *,
    supportive_score: float = 60.0,
    min_samples: int = 10,
) -> dict[str, Any]:
    """Describe historical outcome differences by Fusion component score.

    This is attribution, not causal inference. A component can look helpful simply
    because it tends to appear alongside other strong conditions. The report is
    intentionally advisory and should be used to form hypotheses for later
    walk-forward validation, not to auto-edit LAYER_WEIGHTS.
    """
    resolved: list[dict[str, Any]] = []
    for row in rows:
        label = _resolved_label(row)
        payload = row.get("payload") or {}
        fusion = payload.get("fusion_score") or {}
        components = fusion.get("components") or {}
        if label and isinstance(components, dict):
            resolved.append({"label": label, "components": components})

    overall_wins = sum(1 for row in resolved if row["label"] == "WIN")
    overall_losses = sum(1 for row in resolved if row["label"] == "LOSS")
    overall_rate = _rate(overall_wins, overall_losses)

    names: set[str] = set()
    for row in resolved:
        names.update(str(name) for name in row["components"].keys())

    layers: dict[str, Any] = {}
    for name in sorted(names):
        present_scores: list[float] = []
        present_wins = present_losses = 0
        missing_wins = missing_losses = 0
        supportive_wins = supportive_losses = 0
        weak_wins = weak_losses = 0

        for row in resolved:
            component = row["components"].get(name)
            score = _number(component.get("score")) if isinstance(component, dict) else None
            is_win = row["label"] == "WIN"
            if score is None:
                if is_win:
                    missing_wins += 1
                else:
                    missing_losses += 1
                continue

            present_scores.append(score)
            if is_win:
                present_wins += 1
            else:
                present_losses += 1
            if score >= supportive_score:
                if is_win:
                    supportive_wins += 1
                else:
                    supportive_losses += 1
            else:
                if is_win:
                    weak_wins += 1
                else:
                    weak_losses += 1

        present_n = present_wins + present_losses
        missing_n = missing_wins + missing_losses
        supportive_n = supportive_wins + supportive_losses
        weak_n = weak_wins + weak_losses
        supportive_rate = _rate(supportive_wins, supportive_losses)
        weak_rate = _rate(weak_wins, weak_losses)
        lift = None
        if supportive_rate is not None and weak_rate is not None:
            lift = round(supportive_rate - weak_rate, 1)

        layers[name] = {
            "present_count": present_n,
            "missing_count": missing_n,
            "average_component_score": round(sum(present_scores) / len(present_scores), 1) if present_scores else None,
            "present_win_rate_pct": _rate(present_wins, present_losses),
            "missing_win_rate_pct": _rate(missing_wins, missing_losses),
            "supportive_threshold": float(supportive_score),
            "supportive_count": supportive_n,
            "supportive_win_rate_pct": supportive_rate,
            "below_supportive_count": weak_n,
            "below_supportive_win_rate_pct": weak_rate,
            "supportive_vs_weak_lift_pct_points": lift,
            "enough_samples": supportive_n >= min_samples and weak_n >= min_samples,
        }

    reviewable = [
        {"layer": name, **stats}
        for name, stats in layers.items()
        if stats.get("enough_samples") and stats.get("supportive_vs_weak_lift_pct_points") is not None
    ]
    reviewable.sort(key=lambda item: abs(float(item["supportive_vs_weak_lift_pct_points"])), reverse=True)

    return {
        "resolved_count": len(resolved),
        "overall_target_first_win_rate_pct": overall_rate,
        "supportive_score_threshold": float(supportive_score),
        "minimum_samples_per_side": int(min_samples),
        "layers": layers,
        "review_priority": [
            {
                "layer": item["layer"],
                "lift_pct_points": item["supportive_vs_weak_lift_pct_points"],
                "supportive_count": item["supportive_count"],
                "below_supportive_count": item["below_supportive_count"],
            }
            for item in reviewable
        ],
        "note": (
            "Layer statistics are descriptive correlations, not proof that a layer caused a win or loss. "
            "Do not auto-change Fusion weights from this report; validate proposed changes out of sample."
        ),
    }
