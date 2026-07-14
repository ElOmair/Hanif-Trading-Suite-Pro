from __future__ import annotations
from copy import deepcopy
from itertools import product
import pandas as pd
from strategy import prepare_signals
from backtest import run_backtest

def run_parameter_sweep(data: pd.DataFrame, base: dict) -> pd.DataFrame:
    results = []
    grid = product([75,80,85,90],[18,22,25,30],[1.0,1.2,1.5],
                   [1.0,1.25,1.5],[1.5,2.0,2.5],
                   [(True,False),(False,True),(True,True)])
    for score, adx, rvol, stop_atr, target_r, dirs in grid:
        c = deepcopy(base)
        c.update(minimum_score=score, minimum_adx=adx, minimum_rvol=rvol,
                 stop_atr=stop_atr, target_r=target_r,
                 allow_long=dirs[0], allow_short=dirs[1])
        trades, metrics, _ = run_backtest(prepare_signals(data,c), c)
        results.append({
            "minimum_score":score,"minimum_adx":adx,"minimum_rvol":rvol,
            "stop_atr":stop_atr,"target_r":target_r,
            "allow_long":dirs[0],"allow_short":dirs[1], **metrics
        })
    out = pd.DataFrame(results)
    pf = out["profit_factor"].replace(float("inf"),5).clip(upper=5)
    out["rank_score"] = pf*35 + out["total_return_pct"]*2 + out["average_r"]*20 + out["win_rate_pct"]*.2 + out["max_drawdown_pct"]
    return out.sort_values(["rank_score","profit_factor","total_return_pct"], ascending=False)
