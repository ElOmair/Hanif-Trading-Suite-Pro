from __future__ import annotations

import os
from pathlib import Path

from signal_store import list_signals, record_signal


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
    assert rows[0]["payload"]["fusion_score"]["coverage_pct"] == 65.0


def test_signal_store_can_be_disabled(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("MNT_SIGNAL_DB", str(tmp_path / "disabled.sqlite3"))
    monkeypatch.setenv("MNT_SIGNAL_DB_ENABLED", "false")
    assert record_signal({"symbol": "SPY", "fusion_score": {}}) is None
    assert list_signals("SPY", 10) == []
