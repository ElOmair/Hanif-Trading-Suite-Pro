# Hanif Trading Suite Pro — Phase 3

Research-only QQQ intraday strategy backtester with chronological out-of-sample validation.

## Install

```powershell
py -m pip install -r requirements.txt
```

## Run baseline

```powershell
py main.py
```

## Run optimizer

```powershell
py main.py --optimize
```

The optimizer tests 1,296 configurations and may take several minutes.

## Run Phase 3 validation

```powershell
py main.py --validate
```

Phase 3:

1. Uses the oldest 70% of trading days as training data.
2. Tests 1,296 configurations only on that training period.
3. Rejects configurations with fewer than 10 training trades.
4. Selects the highest-ranked eligible training configuration.
5. Runs it once on the untouched newest 30% of trading days.
6. Grades the out-of-sample result using trade count, profit, average R, profit factor, and drawdown.

## Phase 3 outputs

Files are saved under `output\QQQ\validation`:

- `validation_report.json` — selected configuration, training results, unseen test results, and PASS/FAIL checks
- `top_25_configurations.csv` — best training-period configurations
- `metrics.json` — out-of-sample metrics
- `trades.csv` — out-of-sample trades
- `equity_curve.png` — out-of-sample equity curve
- diagnostic CSV files

## Important

A PASS does not make the strategy ready for live trading. The next gates are a longer historical dataset, repeated walk-forward windows, and paper trading. This software does not place orders.
