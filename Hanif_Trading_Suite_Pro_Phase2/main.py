from __future__ import annotations
import argparse, json
from pathlib import Path
from data_loader import load_yfinance, load_csv
from strategy import prepare_signals
from backtest import run_backtest
from optimizer import run_parameter_sweep
from report import save_report

p = argparse.ArgumentParser()
p.add_argument("--config",default="config.json")
p.add_argument("--csv")
p.add_argument("--symbol")
p.add_argument("--period")
p.add_argument("--interval")
p.add_argument("--optimize",action="store_true")
a = p.parse_args()

with open(a.config,"r",encoding="utf-8") as f:
    c=json.load(f)
if a.symbol: c["symbol"]=a.symbol
if a.period: c["period"]=a.period
if a.interval: c["interval"]=a.interval

if a.csv:
    data=load_csv(a.csv); name=Path(a.csv).stem
else:
    data=load_yfinance(c["symbol"],c["period"],c["interval"]); name=c["symbol"]

signals=prepare_signals(data,c)
trades,metrics,equity=run_backtest(signals,c)
sweep=run_parameter_sweep(data,c) if a.optimize else None
out=Path("output")/name
save_report(out,name,signals,trades,metrics,equity,sweep)

print("\nHANIF TRADING SUITE PRO — PHASE 2 RESULTS")
print("="*52)
for k,v in metrics.items():
    print(f"{k.replace('_',' ').title():24} {v}")
if sweep is not None:
    print("\nTOP 10 CONFIGURATIONS")
    print(sweep.head(10).to_string(index=False))
print(f"\nReports saved to: {out.resolve()}")
