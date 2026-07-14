from __future__ import annotations
import argparse
import json
from pathlib import Path

import pandas as pd

from backtest import run_backtest
from data_loader import load_csv, load_yfinance
from optimizer import run_parameter_sweep
from paper_tracker import initialize_paper_tracker, update_paper_tracker
from report import save_report
from strategy import prepare_signals
from validation import run_out_of_sample_validation
from walk_forward import run_walk_forward_validation

p = argparse.ArgumentParser()
p.add_argument("--config", default="config.json")
p.add_argument("--csv")
p.add_argument("--symbol")
p.add_argument("--period")
p.add_argument("--interval")
mode = p.add_mutually_exclusive_group()
mode.add_argument("--optimize", action="store_true")
mode.add_argument("--validate", action="store_true")
mode.add_argument("--walk-forward", action="store_true")
mode.add_argument("--paper-init", action="store_true")
mode.add_argument("--paper-update", action="store_true")
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

if a.paper_init:
    paper_out = out / "paper"
    summary = initialize_paper_tracker(data, c, paper_out)
    print("\nHANIF TRADING SUITE PRO — PHASE 4 PAPER TRACKER")
    print("=" * 59)
    print("Status                   COLLECTING")
    print(f"Initialized through      {summary['initialized_through']}")
    print(f"Target paper trades      {summary['metrics']['trades_remaining']}")
    print(f"\nRun py main.py --paper-update after each completed market day.")
    print(f"Paper tracker saved to: {paper_out.resolve()}")
elif a.paper_update:
    paper_out = out / "paper"
    summary = update_paper_tracker(data, c, paper_out)
    print("\nHANIF TRADING SUITE PRO — PHASE 4 PAPER UPDATE")
    print("=" * 58)
    print(f"Status                   {summary['status']}")
    for key, value in summary["metrics"].items():
        print(f"{key.replace('_', ' ').title():25} {value}")
    print(f"\nPaper summary saved to: {(paper_out / 'paper_summary.json').resolve()}")
elif a.walk_forward:
    report, trades = run_walk_forward_validation(
        data,
        c,
        initial_train_days=int(c.get("walk_forward_initial_train_days", 20)),
        test_days=int(c.get("walk_forward_test_days", 10)),
        minimum_training_trades=int(c.get("walk_forward_minimum_training_trades", 8)),
        minimum_total_test_trades=int(c.get("walk_forward_minimum_test_trades", 15)),
    )
    walk_out = out / "walk_forward"
    walk_out.mkdir(parents=True, exist_ok=True)
    with open(walk_out / "walk_forward_report.json", "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    trades.to_csv(walk_out / "walk_forward_trades.csv", index=False)
    pd.DataFrame([
        {
            "fold": fold["fold"],
            "training_start": fold["training_start"],
            "training_end": fold["training_end"],
            "test_start": fold["test_start"],
            "test_end": fold["test_end"],
            **fold["selected_configuration"],
            **{f"test_{key}": value for key, value in fold["out_of_sample_metrics"].items()},
        }
        for fold in report["folds"]
    ]).to_csv(walk_out / "fold_summary.csv", index=False)

    print("\nHANIF TRADING SUITE PRO — PHASE 3B WALK-FORWARD")
    print("=" * 62)
    print(f"Status                        {report['status']}")
    for key, value in report["aggregate_out_of_sample_metrics"].items():
        print(f"{key.replace('_', ' ').title():30} {value}")
    print("\nVALIDATION CHECKS")
    for key, value in report["validation_checks"].items():
        print(f"{key.replace('_', ' ').title():45} {'PASS' if value else 'FAIL'}")
    print(f"\nWalk-forward reports saved to: {walk_out.resolve()}")
elif a.validate:
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
