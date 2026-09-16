from __future__ import annotations

from pathlib import Path

from signal_store import calibration_summary, get_signal, list_signals, record_signal, update_signal_outcome


def test_signal_store_round_trip(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "signals.sqlite3"
    monkeypatch.setenv("MNT_SIGNAL_DB", str(db_path))
    monkeypatch.setenv("MNT_SIGNAL_DB_ENABLED", "true")

    signal_id = record_signal(
        {
            "symbol": "NVDA",
            "decision": {"decision": "WATCH"},
            "fusion_score": {
                "direction": "LONG",
                "score": 82.5,
                "coverage_pct": 65.0,
                "grade": "GOOD",
                "beginner_state": "WATCH CLOSELY",
            },
        }
    )
    assert signal_id is not None
    rows = list_signals("NVDA", 10)
    assert len(rows) == 1
    assert rows[0]["symbol"] == "NVDA"
    assert rows[0]["score"] == 82.5
    assert rows[0]["outcome_status"] == "PENDING"
    assert rows[0]["payload"]["fusion_score"]["coverage_pct"] == 65.0


def test_signal_outcome_and_calibration_summary(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "calibration.sqlite3"
    monkeypatch.setenv("MNT_SIGNAL_DB", str(db_path))
    monkeypatch.setenv("MNT_SIGNAL_DB_ENABLED", "true")

    signal_id = record_signal(
        {
            "symbol": "SPY",
            "decision": {"decision": "CONFIRM"},
            "fusion_score": {
                "direction": "LONG",
                "score": 87.0,
                "coverage_pct": 85.0,
                "grade": "STRONG",
                "beginner_state": "GET READY",
            },
        }
    )
    assert signal_id is not None
    assert update_signal_outcome(
        signal_id,
        {
            "calibration_label": "WIN",
            "first_hit": "TARGET_FIRST",
            "directional_return_2h_pct": 0.75,
        },
        "EVALUATED_2H",
    ) is True

    row = get_signal(signal_id)
    assert row is not None
    assert row["outcome_status"] == "EVALUATED_2H"
    assert row["outcome"]["calibration_label"] == "WIN"

    summary = calibration_summary("SPY", 100)
    assert summary["evaluated_count"] == 1
    assert summary["score_buckets"]["80-89"]["wins"] == 1
    assert summary["score_buckets"]["80-89"]["target_first_win_rate_pct"] == 100.0
    assert summary["score_buckets"]["80-89"]["positive_2h_rate_pct"] == 100.0


def test_signal_store_can_be_disabled(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("MNT_SIGNAL_DB", str(tmp_path / "disabled.sqlite3"))
    monkeypatch.setenv("MNT_SIGNAL_DB_ENABLED", "false")
    assert record_signal({"symbol": "SPY", "fusion_score": {}}) is None
    assert list_signals("SPY", 10) == []
