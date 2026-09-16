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
    assert rows[0]["payload"]["execution_gate"]["order_authorized"] is False
    assert rows[0]["payload"]["signal_deduplicated"] is False


def test_record_signal_attaches_review_gate_before_persistence(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("MNT_SIGNAL_DB", str(tmp_path / "gate.sqlite3"))
    monkeypatch.setenv("MNT_SIGNAL_DB_ENABLED", "true")
    payload = {
        "symbol": "SPY",
        "technical": {
            "signal": "LONG",
            "price": 100.0,
            "atr": 2.0,
            "entry_low": 99.5,
            "entry_high": 100.5,
        },
        "decision": {"decision": "CONFIRM"},
        "trade_plan": {"entry_low": 99.5, "entry_high": 100.5},
        "market_gate": {"active": False},
        "fusion_score": {"direction": "LONG", "score": 84.0, "coverage_pct": 80.0},
    }
    signal_id = record_signal(payload)
    assert signal_id is not None
    assert payload["execution_gate"]["state"] == "REVIEW_ENTRY"
    assert payload["execution_gate"]["entry_review_allowed"] is True
    assert payload["execution_gate"]["order_authorized"] is False


def test_repeated_analysis_is_deduplicated(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("MNT_SIGNAL_DB", str(tmp_path / "dedupe.sqlite3"))
    monkeypatch.setenv("MNT_SIGNAL_DB_ENABLED", "true")
    monkeypatch.setenv("MNT_SIGNAL_DEDUPE_MINUTES", "5")
    monkeypatch.setenv("MNT_SIGNAL_DEDUPE_SCORE_DELTA", "3")

    first = {
        "symbol": "SPY",
        "decision": {"decision": "WATCH"},
        "fusion_score": {"direction": "LONG", "score": 80.0, "coverage_pct": 75.0},
    }
    second = {
        "symbol": "SPY",
        "decision": {"decision": "WATCH"},
        "fusion_score": {"direction": "LONG", "score": 81.5, "coverage_pct": 76.0},
    }
    first_id = record_signal(first)
    second_id = record_signal(second)

    assert first_id is not None
    assert second_id == first_id
    assert second["signal_deduplicated"] is True
    assert second["deduplicated_signal_id"] == first_id
    assert len(list_signals("SPY", 10)) == 1


def test_materially_changed_signal_is_not_deduplicated(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("MNT_SIGNAL_DB", str(tmp_path / "changed.sqlite3"))
    monkeypatch.setenv("MNT_SIGNAL_DB_ENABLED", "true")
    monkeypatch.setenv("MNT_SIGNAL_DEDUPE_MINUTES", "5")
    monkeypatch.setenv("MNT_SIGNAL_DEDUPE_SCORE_DELTA", "3")

    first_id = record_signal(
        {
            "symbol": "QQQ",
            "decision": {"decision": "WATCH"},
            "fusion_score": {"direction": "LONG", "score": 70.0, "coverage_pct": 70.0},
        }
    )
    second = {
        "symbol": "QQQ",
        "decision": {"decision": "WATCH"},
        "fusion_score": {"direction": "LONG", "score": 78.0, "coverage_pct": 70.0},
    }
    second_id = record_signal(second)

    assert first_id is not None and second_id is not None
    assert second_id != first_id
    assert second["signal_deduplicated"] is False
    assert len(list_signals("QQQ", 10)) == 2


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


def test_unscorable_neutral_signal_is_excluded_from_calibration(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("MNT_SIGNAL_DB", str(tmp_path / "unscorable.sqlite3"))
    monkeypatch.setenv("MNT_SIGNAL_DB_ENABLED", "true")

    signal_id = record_signal(
        {
            "symbol": "SPY",
            "decision": {"decision": "WATCH"},
            "fusion_score": {"direction": "NEUTRAL", "score": 55.0, "coverage_pct": 80.0},
        }
    )
    assert signal_id is not None
    assert update_signal_outcome(
        signal_id,
        {"calibration_label": "UNRESOLVED", "reason": "Neutral signal."},
        "UNSCORABLE",
    ) is True

    summary = calibration_summary("SPY", 100)
    assert summary["total_count"] == 1
    assert summary["evaluated_count"] == 0
    assert summary["score_buckets"] == {}


def test_signal_store_can_be_disabled_but_gate_still_attaches(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("MNT_SIGNAL_DB", str(tmp_path / "disabled.sqlite3"))
    monkeypatch.setenv("MNT_SIGNAL_DB_ENABLED", "false")
    payload = {"symbol": "SPY", "fusion_score": {}}
    assert record_signal(payload) is None
    assert payload["execution_gate"]["entry_review_allowed"] is False
    assert payload["execution_gate"]["order_authorized"] is False
    assert list_signals("SPY", 10) == []
