from __future__ import annotations

import json

import pandas as pd

import kronos_market_data_bridge as bridge


def test_normalize_schwab_rows_keeps_kronos_csv_shape():
    rows = [
        {
            "time": 1_789_000_000 + i * 300,
            "open": 100 + i,
            "high": 101 + i,
            "low": 99 + i,
            "close": 100.5 + i,
            "volume": 1000 + i,
        }
        for i in range(35)
    ]
    frame = bridge._normalize_schwab_rows(rows)
    assert list(frame.columns) == ["timestamps", "open", "high", "low", "close", "volume"]
    assert len(frame) == 35
    assert frame["timestamps"].dt.tz is None


def test_write_output_matches_existing_kronos_market_data_contract(tmp_path, monkeypatch):
    monkeypatch.setattr(bridge, "DATA_DIR", tmp_path)
    frame = pd.DataFrame(
        {
            "timestamps": pd.date_range("2026-09-17 09:30:00", periods=35, freq="5min"),
            "open": [10.0 + i / 10 for i in range(35)],
            "high": [10.2 + i / 10 for i in range(35)],
            "low": [9.8 + i / 10 for i in range(35)],
            "close": [10.1 + i / 10 for i in range(35)],
            "volume": [1000 + i for i in range(35)],
        }
    )

    output = bridge._write_output("GME", frame, "schwab", None)
    written = pd.read_csv(output)
    assert list(written.columns) == ["timestamps", "open", "high", "low", "close", "volume", "amount"]
    expected_amount = written.loc[0, "volume"] * (
        written.loc[0, "open"] + written.loc[0, "high"] + written.loc[0, "low"] + written.loc[0, "close"]
    ) / 4.0
    assert written.loc[0, "amount"] == expected_amount

    metadata = json.loads((tmp_path / "GME_5m.source.json").read_text(encoding="utf-8"))
    assert metadata["provider"] == "schwab"
    assert metadata["fallback_used"] is False
    assert metadata["bars"] == 35


def test_write_output_records_degraded_fallback(tmp_path, monkeypatch):
    monkeypatch.setattr(bridge, "DATA_DIR", tmp_path)
    frame = pd.DataFrame(
        {
            "timestamps": pd.date_range("2026-09-17 09:30:00", periods=30, freq="5min"),
            "open": [20.0] * 30,
            "high": [20.2] * 30,
            "low": [19.8] * 30,
            "close": [20.1] * 30,
            "volume": [2000] * 30,
        }
    )
    bridge._write_output("SPY", frame, "alpaca_iex", "schwab_not_ready")
    metadata = json.loads((tmp_path / "SPY_5m.source.json").read_text(encoding="utf-8"))
    assert metadata["fallback_used"] is True
    assert metadata["schwab_error"] == "schwab_not_ready"
