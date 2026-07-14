from __future__ import annotations
from pathlib import Path
import json
import matplotlib.pyplot as plt
from diagnostics import build_diagnostics

def save_report(out: Path, symbol, data, trades, metrics, equity, sweep=None):
    out.mkdir(parents=True, exist_ok=True)
    trades.to_csv(out/"trades.csv", index=False)
    data.to_csv(out/"signals.csv")
    with open(out/"metrics.json","w",encoding="utf-8") as f:
        json.dump(metrics,f,indent=2)
    build_diagnostics(trades,out)
    if sweep is not None:
        sweep.to_csv(out/"parameter_sweep.csv",index=False)
        sweep.head(25).to_csv(out/"top_25_configurations.csv",index=False)
    fig, ax = plt.subplots(figsize=(12,6))
    ax.plot(equity.index,equity["Equity"])
    ax.set_title(f"{symbol} Equity Curve")
    ax.set_xlabel("Time"); ax.set_ylabel("Equity")
    fig.tight_layout(); fig.savefig(out/"equity_curve.png",dpi=160); plt.close(fig)
