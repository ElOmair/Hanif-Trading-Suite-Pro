from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd

from paper_tracker import (
    LOCKED_PARAMETERS,
    build_paper_summary,
    completed_trading_days,
    initialize_paper_tracker,
)


def market_data():
    index = pd.to_datetime([
        "2026-07-13 15:55",
        "2026-07-14 10:00",
    ])
    return pd.DataFrame({
        "Open": [100.0, 101.0],
        "High": [100.5, 101.5],
        "Low": [99.5, 100.5],
        "Close": [100.0, 101.0],
        "Volume": [1000, 1000],
    }, index=index)


def base_config():
    return {"starting_capital": 10_000, "paper_target_trades": 20}


def test_incomplete_current_day_is_not_processed():
    now = datetime(2026, 7, 14, 12, 0, tzinfo=ZoneInfo("America/New_York"))

    days = completed_trading_days(market_data(), now)

    assert [str(day.date()) for day in days] == ["2026-07-13"]


def test_initialization_starts_after_latest_completed_day(tmp_path):
    now = datetime(2026, 7, 14, 12, 0, tzinfo=ZoneInfo("America/New_York"))

    summary = initialize_paper_tracker(market_data(), base_config(), tmp_path, now)

    assert summary["status"] == "COLLECTING"
    assert summary["initialized_through"] == "2026-07-13"
    assert summary["metrics"]["trades"] == 0
    assert summary["locked_configuration"] == LOCKED_PARAMETERS


def test_summary_passes_only_after_twenty_profitable_trades():
    trades = pd.DataFrame({
        "pnl": [10.0] * 12 + [-5.0] * 8,
        "r_multiple": [1.0] * 12 + [-0.5] * 8,
    })
    state = {
        "target_trades": 20,
        "starting_capital": 10_000,
        "current_capital": 10_080,
        "initialized_through": "2026-07-13",
        "last_processed_day": "2026-08-13",
        "locked_configuration": LOCKED_PARAMETERS,
    }

    summary = build_paper_summary(trades, state)

    assert summary["status"] == "PASS"
    assert summary["metrics"]["trades"] == 20
    assert summary["metrics"]["net_profit"] == 80.0
    assert summary["validation_checks"]["minimum_20_paper_trades"] is True
