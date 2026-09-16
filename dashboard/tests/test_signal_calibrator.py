from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd

from signal_calibrator import evaluate_signal_row


def _bars(start: datetime, closes: list[float], highs: list[float] | None = None, lows: list[float] | None = None) -> pd.DataFrame:
    highs = highs or [value + 0.2 for value in closes]
    lows = lows or [value - 0.2 for value in closes]
    return pd.DataFrame(
        {
            "timestamps": [(start + timedelta(minutes=5 * (i + 1))).isoformat() for i in range(len(closes))],
            "open": closes,
            "high": highs,
            "low": lows,
            "close": closes,
        }
    )


def test_long_target_first_is_a_win() -> None:
    created = datetime(2026, 9, 16, 14, 0, tzinfo=timezone.utc)
    closes = [100.1 + i * 0.05 for i in range(24)]
    highs = [value + 0.15 for value in closes]
    lows = [value - 0.15 for value in closes]
    highs[5] = 102.2
    signal = {
        "id": 1,
        "created_at": created.isoformat(),
        "direction": "LONG",
        "payload": {"technical": {"price": 100.0}, "trade_plan": {"tp1": 102.0, "stop": 98.0}},
    }
    status, outcome = evaluate_signal_row(signal, _bars(created, closes, highs, lows))
    assert status == "EVALUATED_2H"
    assert outcome["first_hit"] == "TARGET_FIRST"
    assert outcome["calibration_label"] == "WIN"
    assert outcome["directional_return_2h_pct"] > 0


def test_short_stop_first_is_a_loss() -> None:
    created = datetime(2026, 9, 16, 14, 0, tzinfo=timezone.utc)
    closes = [99.9 for _ in range(24)]
    highs = [100.1 for _ in range(24)]
    lows = [99.7 for _ in range(24)]
    highs[2] = 101.2
    signal = {
        "id": 2,
        "created_at": created.isoformat(),
        "direction": "SHORT",
        "payload": {"technical": {"price": 100.0}, "trade_plan": {"tp1": 97.0, "stop": 101.0}},
    }
    status, outcome = evaluate_signal_row(signal, _bars(created, closes, highs, lows))
    assert status == "EVALUATED_2H"
    assert outcome["first_hit"] == "STOP_FIRST"
    assert outcome["calibration_label"] == "LOSS"


def test_signal_stays_pending_until_twelve_future_bars() -> None:
    created = datetime(2026, 9, 16, 14, 0, tzinfo=timezone.utc)
    signal = {
        "id": 3,
        "created_at": created.isoformat(),
        "direction": "LONG",
        "payload": {"technical": {"price": 100.0}},
    }
    status, outcome = evaluate_signal_row(signal, _bars(created, [100.1] * 8))
    assert status == "PENDING"
    assert outcome["bars_available"] == 8
