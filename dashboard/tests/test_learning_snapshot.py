import learning_snapshot


def test_learning_snapshot_only_exposes_aggregate_metrics(monkeypatch):
    monkeypatch.setattr(
        learning_snapshot,
        "build_report",
        lambda limit=2000: {
            "summary": {
                "total": 12,
                "resolved": 8,
                "wins": 5,
                "losses": 3,
                "ambiguous": 1,
                "pending": 3,
                "target_first_win_rate_pct": 62.5,
            },
            "ready_alert_shadow_trades": {"shadow_trades": 6, "resolved": 4},
            "option_contract_shadow_returns": {"horizons": {"60": {"count": 3, "average_return_pct": 12.5}}},
            "policy": {
                "status": "INSUFFICIENT_SAMPLE",
                "current_min_score": 62,
                "recommended_min_score": 62,
                "resolved_samples": 8,
                "minimum_samples_required": 30,
                "target_win_rate_pct": 55,
                "reason": "Need more data",
            },
            "layer_effectiveness": {"technical": {"sample_count": 8}},
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
    assert payload["mode"] == "shadow/research"
    assert payload["learning"]["signal_calibration"]["resolved"] == 8
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
