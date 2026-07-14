from __future__ import annotations

from copy import deepcopy
from math import isfinite
import pandas as pd

from backtest import run_backtest
from optimizer import run_parameter_sweep
from strategy import prepare_signals

PARAMETER_KEYS = (
    "minimum_score", "minimum_adx", "minimum_rvol", "stop_atr",
    "target_r", "allow_long", "allow_short",
)


def split_chronologically(data: pd.DataFrame, train_pct: float = 0.70):
    if not 0.5 <= train_pct <= 0.9:
        raise ValueError("train_pct must be between 0.5 and 0.9")

    days = pd.Index(data.index.normalize().unique()).sort_values()
    if len(days) < 10:
        raise ValueError("At least 10 trading days are required for validation")

    train_days = max(1, min(len(days) - 1, int(len(days) * train_pct)))
    cutoff = days[train_days - 1]
    train = data[data.index.normalize() <= cutoff].copy()
    test = data[data.index.normalize() > cutoff].copy()
    return train, test, cutoff


def select_configuration(sweep: pd.DataFrame, minimum_trades: int = 10) -> dict:
    eligible = sweep[sweep["trades"] >= minimum_trades]
    if eligible.empty:
        raise ValueError(
            f"No optimized configuration produced at least {minimum_trades} training trades"
        )

    row = eligible.iloc[0]
    config = {}
    for key in PARAMETER_KEYS:
        value = row[key]
        if key in {"allow_long", "allow_short"}:
            config[key] = bool(value)
        elif key in {"minimum_score", "minimum_adx"}:
            config[key] = int(value)
        else:
            config[key] = float(value)
    return config


def _finite(value, fallback=0.0):
    number = float(value)
    return number if isfinite(number) else fallback


def run_out_of_sample_validation(
    data: pd.DataFrame,
    base_config: dict,
    train_pct: float = 0.70,
    minimum_trades: int = 10,
):
    train, test, cutoff = split_chronologically(data, train_pct)
    sweep = run_parameter_sweep(train, base_config)
    selected = select_configuration(sweep, minimum_trades)

    chosen = deepcopy(base_config)
    chosen.update(selected)

    train_signals = prepare_signals(train, chosen)
    train_trades, train_metrics, _ = run_backtest(train_signals, chosen)

    # Calculate indicators across the full chronological series, then slice the
    # untouched test period. This preserves indicator warm-up without using
    # future observations to choose the configuration.
    all_signals = prepare_signals(data, chosen)
    test_signals = all_signals.loc[test.index]
    test_trades, test_metrics, test_equity = run_backtest(test_signals, chosen)

    checks = {
        "minimum_5_test_trades": int(test_metrics["trades"]) >= 5,
        "positive_test_profit": float(test_metrics["net_profit"]) > 0,
        "positive_test_average_r": float(test_metrics["average_r"]) > 0,
        "test_profit_factor_at_least_1_10": _finite(test_metrics["profit_factor"], 99.0) >= 1.10,
        "test_drawdown_not_worse_than_5_pct": float(test_metrics["max_drawdown_pct"]) >= -5.0,
    }
    passed = all(checks.values())

    report = {
        "status": "PASS" if passed else "FAIL",
        "train_split_pct": train_pct,
        "training_start": str(train.index.min()),
        "training_end": str(train.index.max()),
        "test_start": str(test.index.min()),
        "test_end": str(test.index.max()),
        "selected_configuration": selected,
        "training_metrics": train_metrics,
        "out_of_sample_metrics": test_metrics,
        "validation_checks": checks,
    }
    return report, sweep, test_signals, test_trades, test_equity
