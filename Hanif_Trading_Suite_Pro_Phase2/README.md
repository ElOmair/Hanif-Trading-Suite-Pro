# Hanif Trading Suite Pro — Phase 3B

Research-only QQQ intraday strategy backtester with chronological validation.

## Install

```powershell
py -m pip install -r requirements.txt
```

## Commands

```powershell
py main.py
py main.py --optimize
py main.py --validate
py main.py --walk-forward
```

- `--optimize`: tests 1,296 configurations on the complete dataset.
- `--validate`: performs one 70% training / 30% unseen test split.
- `--walk-forward`: performs repeated expanding-window validation.

## Phase 3B walk-forward method

`py main.py --walk-forward`:

1. Starts with 20 training days.
2. Optimizes 1,296 configurations using training data only.
3. Rejects configurations with fewer than 8 training trades.
4. Tests the selected configuration on the next untouched 10 days.
5. Expands training by 10 days and repeats.
6. Keeps test windows non-overlapping so unseen trades are not double-counted.
7. Combines every out-of-sample trade into one final result.

The final PASS gate requires:

- at least 3 completed folds
- at least 15 combined unseen trades
- positive combined profit
- positive combined average R
- at least 60% profitable folds
- no fold worse than a 5% drawdown

This process runs the optimizer multiple times and can take considerably longer than `--optimize`.

## Phase 3B outputs

Files are saved under `output\QQQ\walk_forward`:

- `walk_forward_report.json` — final PASS/FAIL, aggregate metrics, and every fold
- `walk_forward_trades.csv` — combined unseen trades
- `fold_summary.csv` — compact comparison of each test window and selected configuration

## Important

A PASS does not authorize live trading. The next gates are longer historical data and paper trading. This software does not connect to a broker or place orders.
