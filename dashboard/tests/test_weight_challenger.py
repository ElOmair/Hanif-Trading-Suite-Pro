from datetime import datetime, timedelta, timezone

from mnt_engine import LAYER_WEIGHTS
from weight_challenger import build_candidate_weights, score_with_weights, walk_forward_weight_challenge


LAYERS = list(LAYER_WEIGHTS)


def _row(index: int, label: str, technical_score: float) -> dict:
    components = {}
    for name in LAYERS:
        components[name] = {"score": technical_score if name == "technical" else 65.0}
    return {
        "created_at": (datetime(2026, 1, 2, tzinfo=timezone.utc) + timedelta(minutes=index)).isoformat(),
        "outcome": {"calibration_label": label},
        "payload": {"fusion_score": {"components": components}},
    }


def _history(count: int = 80) -> list[dict]:
    rows = []
    for index in range(count):
        label = "WIN" if index % 2 == 0 else "LOSS"
        rows.append(_row(index, label, 80.0 if label == "WIN" else 53.2))
    return rows


def test_score_with_weights_reweights_only_available_components():
    row = _row(1, "WIN", 80.0)
    del row["payload"]["fusion_score"]["components"]["gamma"]
    score, coverage = score_with_weights(row, LAYER_WEIGHTS)
    assert score is not None
    assert 0 < coverage < 100


def test_candidate_weight_changes_are_small_and_do_not_mutate_live_weights():
    current = dict(LAYER_WEIGHTS)
    proposal = build_candidate_weights(_history(60), current_weights=current, min_samples_per_side=10)
    assert proposal["changes"]
    assert any(item["layer"] == "technical" and item["raw_weight_delta"] > 0 for item in proposal["changes"])
    assert current == LAYER_WEIGHTS
    assert round(sum(proposal["candidate_weights"].values()), 6) == round(sum(current.values()), 6)
    for name, value in proposal["candidate_weights"].items():
        assert value >= 1.0
        assert name in current


def test_walk_forward_challenger_uses_later_holdout_and_can_validate_candidate():
    report = walk_forward_weight_challenge(
        _history(80),
        min_resolved=40,
        min_holdout=12,
        min_candidate_selected=8,
        min_holdout_improvement_pct_points=3.0,
    )
    assert report["training_count"] == 56
    assert report["holdout_count"] == 24
    assert report["baseline_holdout"]["selected"] == 24
    assert report["candidate_holdout"]["selected"] == 12
    assert report["candidate_holdout"]["win_rate_pct"] == 100.0
    assert report["recommend_candidate"] is True
    assert report["status"] == "CANDIDATE_VALIDATED"


def test_walk_forward_challenger_collects_before_minimum_sample():
    report = walk_forward_weight_challenge(_history(20), min_resolved=40)
    assert report["status"] == "COLLECTING"
    assert report["recommend_candidate"] is False
