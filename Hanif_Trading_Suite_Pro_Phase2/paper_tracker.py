from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from backtest import run_backtest
from strategy import prepare_signals

LOCKED_PARAMETERS = {
    "minimum_score": 80,
    "minimum_adx": 30,
    "minimum_rvol": 1.0,
    "stop_atr": 1.5,
    "target_r": 2.5,
    "allow_long": True,
    "allow_short": False,
}

TRADE_COLUMNS = [
    "direction", "setup_type", "entry_time", "exit_time", "hour", "entry",
    "exit", "stop", "target", "quantity", "pnl", "r_multiple",
    "exit_reason", "score", "adx", "rvol",
]


def _paths(out: Path):
    return {
        "state": out / "paper_state.json",
        "trades": out / "paper_trades.csv",
        "summary": out / "paper_summary.json",
    }


def completed_trading_days(data: pd.DataFrame, now: datetime | None = None):
    now_et = now or datetime.now(ZoneInfo("America/New_York"))
    if now_et.tzinfo is None:
        now_et = now_et.replace(tzinfo=ZoneInfo("America/New_York"))

    days = pd.Index(data.index.normalize().unique()).sort_values()
    completed = []
    for day in days:
        if day.date() < now_et.date():
            completed.append(day)
        elif day.date() == now_et.date():
            final_bar = data[data.index.normalize() == day].index.max()
            if final_bar.time().strftime("%H:%M") >= "15:55":
                completed.append(day)
    return pd.Index(completed)


def initialize_paper_tracker(
    data: pd.DataFrame,
    base_config: dict,
    out: Path,
    now: datetime | None = None,
):
    paths = _paths(out)
    if paths["state"].exists():
        raise FileExistsError(
            f"Paper tracker already exists at {paths['state']}. "
            "Use --paper-update instead."
        )

    out.mkdir(parents=True, exist_ok=True)
    completed = completed_trading_days(data, now)
    if completed.empty:
        raise ValueError("No completed trading day is available for initialization")

    starting_capital = float(base_config["starting_capital"])
    state = {
        "created_at": (now or datetime.now(ZoneInfo("America/New_York"))).isoformat(),
        "initialized_through": str(completed[-1].date()),
        "last_processed_day": str(completed[-1].date()),
        "starting_capital": starting_capital,
        "current_capital": starting_capital,
        "target_trades": int(base_config.get("paper_target_trades", 20)),
        "locked_configuration": LOCKED_PARAMETERS,
    }
    with open(paths["state"], "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)
    pd.DataFrame(columns=TRADE_COLUMNS).to_csv(paths["trades"], index=False)
    summary = build_paper_summary(pd.DataFrame(columns=TRADE_COLUMNS), state)
    with open(paths["summary"], "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    return summary


def build_paper_summary(trades: pd.DataFrame, state: dict):
    target = int(state["target_trades"])
    starting_capital = float(state["starting_capital"])

    if trades.empty:
        metrics = {
            "starting_capital": starting_capital,
            "ending_capital": float(state["current_capital"]),
            "net_profit": 0.0,
            "total_return_pct": 0.0,
            "trades": 0,
            "trades_remaining": target,
            "win_rate_pct": 0.0,
            "profit_factor": None,
            "average_r": 0.0,
            "max_drawdown_pct": 0.0,
        }
    else:
        pnl = pd.to_numeric(trades["pnl"])
        r_values = pd.to_numeric(trades["r_multiple"])
        gross_profit = pnl[pnl > 0].sum()
        gross_loss = abs(pnl[pnl < 0].sum())
        equity = starting_capital + pnl.cumsum()
        peak = pd.concat([
            pd.Series([starting_capital]),
            equity.reset_index(drop=True),
        ]).cummax().iloc[1:]
        drawdown = (equity.reset_index(drop=True) - peak.reset_index(drop=True)) / peak.reset_index(drop=True)
        metrics = {
            "starting_capital": round(starting_capital, 2),
            "ending_capital": round(starting_capital + float(pnl.sum()), 2),
            "net_profit": round(float(pnl.sum()), 2),
            "total_return_pct": round(float(pnl.sum()) / starting_capital * 100, 2),
            "trades": int(len(trades)),
            "trades_remaining": max(0, target - len(trades)),
            "win_rate_pct": round(float((pnl > 0).mean() * 100), 2),
            "profit_factor": round(float(gross_profit / gross_loss), 2) if gross_loss else None,
            "average_r": round(float(r_values.mean()), 2),
            "max_drawdown_pct": round(float(drawdown.min() * 100), 2),
        }

    enough_trades = metrics["trades"] >= target
    profit_factor_ok = metrics["profit_factor"] is None or metrics["profit_factor"] >= 1.2
    checks = {
        f"minimum_{target}_paper_trades": enough_trades,
        "positive_net_profit": metrics["net_profit"] > 0,
        "positive_average_r": metrics["average_r"] > 0,
        "profit_factor_at_least_1_20": profit_factor_ok,
        "drawdown_not_worse_than_5_pct": metrics["max_drawdown_pct"] >= -5,
    }
    if not enough_trades:
        status = "COLLECTING"
    else:
        status = "PASS" if all(checks.values()) else "FAIL"

    return {
        "status": status,
        "mode": "paper tracking only; no orders are placed",
        "locked_configuration": state["locked_configuration"],
        "initialized_through": state["initialized_through"],
        "last_processed_day": state["last_processed_day"],
        "metrics": metrics,
        "validation_checks": checks,
    }


def update_paper_tracker(
    data: pd.DataFrame,
    base_config: dict,
    out: Path,
    now: datetime | None = None,
):
    paths = _paths(out)
    if not paths["state"].exists():
        raise FileNotFoundError("Run py main.py --paper-init before --paper-update")

    with open(paths["state"], "r", encoding="utf-8") as f:
        state = json.load(f)
    existing = pd.read_csv(paths["trades"]) if paths["trades"].exists() else pd.DataFrame(columns=TRADE_COLUMNS)

    completed = completed_trading_days(data, now)
    last_day = pd.Timestamp(state["last_processed_day"])
    new_days = completed[completed > last_day]

    chosen = deepcopy(base_config)
    chosen.update(state["locked_configuration"])
    all_signals = prepare_signals(data, chosen)

    new_trade_frames = []
    capital = float(state["current_capital"])
    for day in new_days:
        day_signals = all_signals[all_signals.index.normalize() == day]
        daily_config = deepcopy(chosen)
        daily_config["starting_capital"] = capital
        trades, metrics, _ = run_backtest(day_signals, daily_config)
        capital = float(metrics["ending_capital"])
        if not trades.empty:
            new_trade_frames.append(trades)
        state["last_processed_day"] = str(day.date())

    if new_trade_frames:
        new_trades = pd.concat(new_trade_frames, ignore_index=True)
        combined = pd.concat([existing, new_trades], ignore_index=True)
        combined = combined.drop_duplicates(
            subset=["direction", "entry_time", "exit_time"],
            keep="last",
        )
    else:
        combined = existing

    state["current_capital"] = round(capital, 2)
    combined.to_csv(paths["trades"], index=False)
    with open(paths["state"], "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)

    summary = build_paper_summary(combined, state)
    with open(paths["summary"], "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    return summary
