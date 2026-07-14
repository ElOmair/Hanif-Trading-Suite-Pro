from __future__ import annotations
from pathlib import Path
import pandas as pd

def summarize(g):
    if g.empty:
        return pd.Series(dtype=float)
    gp = g.loc[g.pnl > 0, "pnl"].sum()
    gl = abs(g.loc[g.pnl < 0, "pnl"].sum())
    return pd.Series({
        "trades": len(g),
        "win_rate_pct": round((g.pnl > 0).mean()*100,2),
        "net_profit": round(g.pnl.sum(),2),
        "profit_factor": round(gp/gl,2) if gl else float("inf"),
        "average_r": round(g.r_multiple.mean(),2)
    })

def build_diagnostics(trades: pd.DataFrame, out: Path):
    if trades.empty:
        return
    trades.groupby("direction").apply(summarize, include_groups=False).to_csv(out/"diagnostic_by_direction.csv")
    trades.groupby("setup_type").apply(summarize, include_groups=False).to_csv(out/"diagnostic_by_setup.csv")
    trades.groupby("hour").apply(summarize, include_groups=False).to_csv(out/"diagnostic_by_hour.csv")

    specs = [
        ("score","score_band",[0,74,79,84,89,100],["<75","75-79","80-84","85-89","90-100"]),
        ("adx","adx_band",[0,19.99,24.99,29.99,39.99,999],["<20","20-24.9","25-29.9","30-39.9","40+"]),
        ("rvol","rvol_band",[0,.99,1.19,1.49,1.99,999],["<1.0","1.0-1.19","1.2-1.49","1.5-1.99","2.0+"])
    ]
    for col, band, bins, labels in specs:
        trades[band] = pd.cut(trades[col], bins, labels=labels, include_lowest=True)
        trades.groupby(band, observed=False).apply(summarize, include_groups=False).to_csv(out/f"diagnostic_by_{col}.csv")
