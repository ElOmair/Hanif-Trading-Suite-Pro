from __future__ import annotations
import argparse
import json
from pathlib import Path

from backtest import run_backtest
from data_loader import load_csv, load_yfinance
from optimizer import run_parameter_sweep
from report import save_report
from strategy import prepare_signals
from validation import run_out_of_sample_validation

p = argparse.ArgumentParser()
p.add_argument("--config", default="config.json")
p.add_argument("--csv")
p.add_argument("--symbol")
p.add_argument("--period")
p.add_argument("--interval")
mode = p.add_mutually_exclusive_group()
mode.add_argument("--optimize", action="store_true")
mode.add_argument("--validate", action="store_true")
a = p.parse_args()

with open(a.config, "r", encoding="utf-8") as f:
    c = json.load(f)
if a.symbol:
    c["symbol"] = a.symbol
if a.period:
    c["period"] = a.period
if a.interval:
    c["interval"] = a.interval

if a.csv:
    data = load_csv(a.csv)
    name = Path(a.csv).stem
else:
    data = load_yfinance(c["symbol"], c["period"], c["interval"])
    name = c["symbol"]

out = Path("output") / name

if a.validate:
    report, sweep, signals, trades, equity = run_out_of_sample_validation(
        data,
        c,
        train_pct=float(c.get("train_split_pct", 0.70)),
        minimum_trades=int(c.get("validation_minimum_training_trades", 10)),
    )
    validation_out = out / "validation"
    save_report(
        validation_out,
        name,
        signals,
        trades,
        report["out_of_sample_metrics"],
        equity,
        sweep,
    )
    with open(validation_out / "validation_report.json", "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    print("\nHANIF TRADING SUITE PRO — PHASE 3 VALIDATION")
    print("=" * 58)
    print(f"Status                   {report['status']}")
    print(f"Training period          {report['training_start']} to {report['training_end']}")
    print(f"Out-of-sample period     {report['test_start']} to {report['test_end']}")
    print("\nSELECTED CONFIGURATION")
    for key, value in report["selected_configuration"].items():
        print(f"{key.replace('_', ' ').title():25} {value}")
    print("\nOUT-OF-SAMPLE RESULTS")
    for key, value in report["out_of_sample_metrics"].items():
        print(f"{key.replace('_', ' ').title():25} {value}")
    print(f"\nValidation reports saved to: {validation_out.resolve()}")
else:
    signals = prepare_signals(data, c)
    trades, metrics, equity = run_backtest(signals, c)
    sweep = run_parameter_sweep(data, c) if a.optimize else None
    save_report(out, name, signals, trades, metrics, equity, sweep)

    print("\nHANIF TRADING SUITE PRO — PHASE 2 RESULTS")
    print("=" * 52)
    for key, value in metrics.items():
        print(f"{key.replace('_', ' ').title():24} {value}")
    if sweep is not None:
        print("\nTOP 10 CONFIGURATIONS")
        print(sweep.head(10).to_string(index=False))
    print(f"\nReports saved to: {out.resolve()}")
