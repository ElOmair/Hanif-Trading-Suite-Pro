from __future__ import annotations

from copy import deepcopy
import pandas as pd

from backtest import run_backtest
from optimizer import run_parameter_sweep
from strategy import prepare_signals
from validation import select_configuration


def build_walk_forward_folds(
    data: pd.DataFrame,
    initial_train_days: int = 20,
    test_days: int = 10,
):
    days = pd.Index(data.index.normalize().unique()).sort_values()
    if initial_train_days < 10:
        raise ValueError("initial_train_days must be at least 10")
    if test_days < 5:
        raise ValueError("test_days must be at least 5")
    if len(days) < initial_train_days + test_days:
        raise ValueError("Not enough trading days for one walk-forward fold")

    folds = []
    train_end = initial_train_days
    while train_end + test_days <= len(days):
        train_day_set = days[:train_end]
        test_day_set = days[train_end:train_end + test_days]
        train = data[data.index.normalize().isin(train_day_set)].copy()
        test = data[data.index.normalize().isin(test_day_set)].copy()
        folds.append((train, test))
        train_end += test_days
    return folds


def _aggregate_metrics(trades: pd.DataFrame, fold_metrics: list[dict], starting_capital: float):
    if trades.empty:
        return {
            "starting_capital": starting_capital,
            "net_profit": 0.0,
            "total_return_pct": 0.0,
            "trades": 0,
            "win_rate_pct": 0.0,
            "profit_factor": 0.0,
            "average_r": 0.0,
            "worst_fold_drawdown_pct": 0.0,
            "profitable_folds": 0,
            "total_folds": len(fold_metrics),
            "profitable_fold_pct": 0.0,
        }

    gross_profit = trades.loc[trades["pnl"] > 0, "pnl"].sum()
    gross_loss = abs(trades.loc[trades["pnl"] < 0, "pnl"].sum())
    net_profit = trades["pnl"].sum()
    profitable_folds = sum(float(m["net_profit"]) > 0 for m in fold_metrics)
    total_folds = len(fold_metrics)
    return {
        "starting_capital": round(starting_capital, 2),
        "net_profit": round(float(net_profit), 2),
        "total_return_pct": round(float(net_profit) / starting_capital * 100, 2),
        "trades": int(len(trades)),
        "win_rate_pct": round(float((trades["pnl"] > 0).mean() * 100), 2),
        "profit_factor": round(float(gross_profit / gross_loss), 2) if gross_loss else None,
        "average_r": round(float(trades["r_multiple"].mean()), 2),
        "worst_fold_drawdown_pct": round(
            min(float(m["max_drawdown_pct"]) for m in fold_metrics), 2
        ),
        "profitable_folds": profitable_folds,
        "total_folds": total_folds,
        "profitable_fold_pct": round(profitable_folds / total_folds * 100, 2),
    }


def run_walk_forward_validation(
    data: pd.DataFrame,
    base_config: dict,
    initial_train_days: int = 20,
    test_days: int = 10,
    minimum_training_trades: int = 8,
    minimum_total_test_trades: int = 15,
):
    folds = build_walk_forward_folds(data, initial_train_days, test_days)
    fold_reports = []
    trade_frames = []

    for fold_number, (train, test) in enumerate(folds, start=1):
        sweep = run_parameter_sweep(train, base_config)
        selected = select_configuration(sweep, minimum_training_trades)
        chosen = deepcopy(base_config)
        chosen.update(selected)

        training_signals = prepare_signals(train, chosen)
        _, training_metrics, _ = run_backtest(training_signals, chosen)

        available = data[data.index <= test.index.max()]
        available_signals = prepare_signals(available, chosen)
        test_signals = available_signals.loc[test.index]
        test_trades, test_metrics, _ = run_backtest(test_signals, chosen)

        if not test_trades.empty:
            tagged = test_trades.copy()
            tagged.insert(0, "fold", fold_number)
            trade_frames.append(tagged)

        fold_reports.append({
            "fold": fold_number,
            "training_start": str(train.index.min()),
            "training_end": str(train.index.max()),
            "test_start": str(test.index.min()),
            "test_end": str(test.index.max()),
            "selected_configuration": selected,
            "training_metrics": training_metrics,
            "out_of_sample_metrics": test_metrics,
        })

    combined_trades = (
        pd.concat(trade_frames, ignore_index=True)
        if trade_frames
        else pd.DataFrame()
    )
    aggregate = _aggregate_metrics(
        combined_trades,
        [fold["out_of_sample_metrics"] for fold in fold_reports],
        float(base_config["starting_capital"]),
    )

    checks = {
        "minimum_3_folds": aggregate["total_folds"] >= 3,
        f"minimum_{minimum_total_test_trades}_combined_test_trades":
            aggregate["trades"] >= minimum_total_test_trades,
        "positive_combined_profit": aggregate["net_profit"] > 0,
        "positive_combined_average_r": aggregate["average_r"] > 0,
        "at_least_60_pct_profitable_folds": aggregate["profitable_fold_pct"] >= 60,
        "no_fold_drawdown_worse_than_5_pct":
            aggregate["worst_fold_drawdown_pct"] >= -5,
    }

    report = {
        "status": "PASS" if all(checks.values()) else "FAIL",
        "method": "expanding-window walk-forward with non-overlapping test periods",
        "initial_train_days": initial_train_days,
        "test_days_per_fold": test_days,
        "minimum_training_trades": minimum_training_trades,
        "minimum_combined_test_trades": minimum_total_test_trades,
        "aggregate_out_of_sample_metrics": aggregate,
        "validation_checks": checks,
        "folds": fold_reports,
    }
    return report, combined_trades
