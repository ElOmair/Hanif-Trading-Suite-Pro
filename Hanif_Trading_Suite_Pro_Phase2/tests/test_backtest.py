import pandas as pd

from backtest import run_backtest


def config(starting_capital=1_000):
    return {
        "starting_capital": starting_capital,
        "risk_per_trade_pct": 10,
        "stop_atr": 1,
        "target_r": 2,
        "max_trades_per_day": 3,
        "slippage_per_share": 0,
        "commission_per_trade": 0,
    }


def bars(prices, signal_on_first=True):
    index = pd.to_datetime([time for time, _ in prices])
    close = [price for _, price in prices]
    frame = pd.DataFrame({
        "Open": close,
        "High": [price + 0.1 for price in close],
        "Low": [price - 0.1 for price in close],
        "Close": close,
        "ATR": [1.0] * len(close),
        "LONG_SIGNAL": [signal_on_first] + [False] * (len(close) - 1),
        "SHORT_SIGNAL": [False] * len(close),
        "BULL_SCORE": [90] * len(close),
        "BEAR_SCORE": [0] * len(close),
        "LONG_SETUP_TYPE": ["PULLBACK"] * len(close),
        "SHORT_SETUP_TYPE": ["NONE"] * len(close),
        "ADX": [30.0] * len(close),
        "RVOL": [1.5] * len(close),
    }, index=index)
    return frame


def test_position_closes_on_last_bar_of_day():
    data = bars([
        ("2026-07-13 15:55", 100.0),
        ("2026-07-13 16:00", 100.5),
        ("2026-07-14 09:30", 101.0),
    ])

    trades, _, _ = run_backtest(data, config())

    assert len(trades) == 1
    assert trades.iloc[0]["exit_reason"] == "END_OF_DAY"
    assert trades.iloc[0]["exit_time"].startswith("2026-07-13")


def test_quantity_is_capped_by_available_buying_power():
    data = bars([
        ("2026-07-13 09:30", 600.0),
        ("2026-07-13 16:00", 600.5),
    ])

    trades, _, _ = run_backtest(data, config(starting_capital=1_000))

    assert len(trades) == 1
    assert trades.iloc[0]["quantity"] == 1


def test_trade_is_skipped_when_one_share_is_unaffordable():
    data = bars([
        ("2026-07-13 09:30", 1_100.0),
        ("2026-07-13 16:00", 1_101.0),
    ])

    trades, metrics, _ = run_backtest(data, config(starting_capital=1_000))

    assert trades.empty
    assert metrics["trades"] == 0
