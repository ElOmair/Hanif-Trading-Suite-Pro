import learning_snapshot


def test_learning_snapshot_only_exposes_aggregate_metrics(monkeypatch):
    monkeypatch.setattr(
        learning_snapshot,
        "build_report",
        lambda limit=2000: {
            "summary": {
                "total_count": 12,
                "evaluated_count": 9,
                "score_buckets": {
                    "70-79": {"wins": 3, "losses": 2, "ambiguous": 1, "unresolved": 0},
                    "80-89": {"wins": 2, "losses": 1, "ambiguous": 0, "unresolved": 0},
                },
            },
            "ready_alert_shadow_trades": {"shadow_trades": 6, "resolved": 4},
            "option_contract_shadow_returns": {"horizons": {"60": {"count": 3, "average_return_pct": 12.5}}},
            "policy": {
                "status": "SHADOW_LEARNING",
                "resolved_count": 8,
                "minimum_resolved_samples": 30,
                "target_win_rate_pct": 55,
                "current": {"min_score": 62, "min_coverage_pct": 55},
                "recommended": {"min_score": 62, "min_coverage_pct": 55},
                "score_delta": 0,
                "reason": "Need more data",
            },
            "layer_effectiveness": {"technical": {"sample_count": 8}},
            "weight_challenge": {
                "status": "KEEP_CURRENT",
                "resolved": 50,
                "training_count": 35,
                "holdout_count": 15,
                "recommend_candidate": False,
                "holdout_improvement_pct_points": 1.0,
                "baseline_holdout": {"selected": 10, "win_rate_pct": 60.0},
                "candidate_holdout": {"selected": 10, "win_rate_pct": 61.0},
                "proposed_changes": [{"layer": "technical", "raw_weight_delta": 2.0}],
                "current_weights": {"technical": 25.0},
                "candidate_weights": {"technical": 27.0},
                "reason": "Keep current",
            },
        },
    )
    worker = {
        "worker_state": "HEALTHY",
        "heartbeat_at": "2026-09-17T00:00:00+00:00",
        "radar": {"shortlist": ["SPY", "NVDA"]},
        "session_risk": {"state": "NORMAL"},
        "secret": "must-not-leak",
    }
    payload = learning_snapshot.build_learning_snapshot(worker)
    encoded = str(payload)
    calibration = payload["learning"]["signal_calibration"]
    threshold = payload["learning"]["threshold_policy"]
    challenge = payload["learning"]["weight_challenge"]
    assert payload["mode"] == "shadow/research"
    assert calibration["resolved"] == 8
    assert calibration["wins"] == 5
    assert calibration["losses"] == 3
    assert calibration["target_first_win_rate_pct"] == 62.5
    assert threshold["current_min_score"] == 62
    assert threshold["recommended_min_score"] == 62
    assert challenge["status"] == "KEEP_CURRENT"
    assert challenge["holdout_count"] == 15
    assert challenge["recommend_candidate"] is False
    assert payload["learning"]["option_contract_returns"]["horizons"]["60"]["count"] == 3
    assert payload["worker"]["radar"]["shortlist"] == ["SPY", "NVDA"]
    assert "must-not-leak" not in encoded


def test_learning_snapshot_writes_atomically(monkeypatch, tmp_path):
    monkeypatch.setattr(
        learning_snapshot,
        "build_learning_snapshot",
        lambda worker_status=None: {"mode": "shadow/research", "worker": worker_status or {}},
    )
    path = tmp_path / "mnt-runtime.json"
    written = learning_snapshot.write_learning_snapshot({"worker_state": "OFF_HOURS"}, path)
    assert written == path
    assert path.exists()
    assert not (tmp_path / "mnt-runtime.json.tmp").exists()
    assert "OFF_HOURS" in path.read_text(encoding="utf-8")
