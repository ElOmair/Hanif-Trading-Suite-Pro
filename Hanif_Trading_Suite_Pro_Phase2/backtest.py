from __future__ import annotations
from dataclasses import dataclass, asdict
import math
import pandas as pd

@dataclass
class Trade:
    direction: str
    setup_type: str
    entry_time: str
    exit_time: str
    hour: int
    entry: float
    exit: float
    stop: float
    target: float
    quantity: int
    pnl: float
    r_multiple: float
    exit_reason: str
    score: int
    adx: float
    rvol: float

def run_backtest(df: pd.DataFrame, c: dict):
    capital = float(c["starting_capital"])
    initial = capital
    risk_pct = float(c["risk_per_trade_pct"]) / 100
    stop_atr = float(c["stop_atr"])
    target_r = float(c["target_r"])
    slip = float(c.get("slippage_per_share", 0))
    commission = float(c.get("commission_per_trade", 0))
    max_day = int(c.get("max_trades_per_day", 999))
    trades, equity, position, day_counts = [], [], None, {}

    for ts, row in df.iterrows():
        day = ts.date()
        day_counts.setdefault(day, 0)
        equity.append({"Time": ts, "Equity": capital})

        if position:
            d = position["direction"]
            stop_hit = row["Low"] <= position["stop"] if d == "LONG" else row["High"] >= position["stop"]
            target_hit = row["High"] >= position["target"] if d == "LONG" else row["Low"] <= position["target"]
            if stop_hit or target_hit:
                exit_price = position["stop"] if stop_hit else position["target"]
                reason = "STOP" if stop_hit else "TARGET"
                exit_price += slip if d == "SHORT" else -slip
                pnl = ((exit_price - position["entry"]) if d == "LONG" else (position["entry"] - exit_price)) * position["quantity"] - commission
                risk_dollars = abs(position["entry"] - position["stop"]) * position["quantity"]
                capital += pnl
                trades.append(Trade(
                    d, position["setup_type"], str(position["entry_time"]), str(ts),
                    int(position["entry_time"].hour), round(position["entry"],4),
                    round(exit_price,4), round(position["stop"],4), round(position["target"],4),
                    position["quantity"], round(pnl,2),
                    round(pnl/risk_dollars if risk_dollars else 0,2), reason,
                    position["score"], round(position["adx"],2), round(position["rvol"],2)
                ))
                position = None
                continue

        if position is None and day_counts[day] < max_day and pd.notna(row.get("ATR")) and row["ATR"] > 0:
            direction = None
            if bool(row.get("LONG_SIGNAL", False)):
                direction, score, setup_type = "LONG", int(row["BULL_SCORE"]), row["LONG_SETUP_TYPE"]
            elif bool(row.get("SHORT_SIGNAL", False)):
                direction, score, setup_type = "SHORT", int(row["BEAR_SCORE"]), row["SHORT_SETUP_TYPE"]

            if direction:
                entry = float(row["Close"]) + (slip if direction == "LONG" else -slip)
                risk_share = float(row["ATR"]) * stop_atr
                qty = max(1, math.floor((capital * risk_pct) / risk_share))
                stop = entry - risk_share if direction == "LONG" else entry + risk_share
                target = entry + risk_share * target_r if direction == "LONG" else entry - risk_share * target_r
                position = dict(direction=direction, entry_time=ts, entry=entry, stop=stop,
                                target=target, quantity=qty, score=score, setup_type=setup_type,
                                adx=float(row["ADX"]), rvol=float(row["RVOL"]) if pd.notna(row["RVOL"]) else 0.0)
                day_counts[day] += 1

    trade_df = pd.DataFrame([asdict(t) for t in trades])
    equity_df = pd.DataFrame(equity).set_index("Time")
    if trade_df.empty:
        return trade_df, {
            "starting_capital": initial, "ending_capital": capital, "net_profit": 0.0,
            "total_return_pct": 0.0, "trades": 0, "win_rate_pct": 0.0,
            "profit_factor": 0.0, "average_r": 0.0, "max_drawdown_pct": 0.0
        }, equity_df

    gp = trade_df.loc[trade_df.pnl > 0, "pnl"].sum()
    gl = abs(trade_df.loc[trade_df.pnl < 0, "pnl"].sum())
    peak = equity_df["Equity"].cummax()
    dd = (equity_df["Equity"] - peak) / peak
    metrics = {
        "starting_capital": round(initial,2),
        "ending_capital": round(capital,2),
        "net_profit": round(capital-initial,2),
        "total_return_pct": round((capital/initial-1)*100,2),
        "trades": int(len(trade_df)),
        "win_rate_pct": round((trade_df.pnl > 0).mean()*100,2),
        "profit_factor": round(gp/gl,2) if gl else float("inf"),
        "average_r": round(trade_df.r_multiple.mean(),2),
        "max_drawdown_pct": round(dd.min()*100,2)
    }
    return trade_df, metrics, equity_df
