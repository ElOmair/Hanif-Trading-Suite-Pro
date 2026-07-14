# Hanif Trading Suite Pro — Phase 4

Research-only QQQ intraday strategy validation and paper tracker. It does not connect to a broker or place orders.

## Install

```powershell
py -m pip install -r requirements.txt
```

## Historical validation commands

```powershell
py main.py
py main.py --optimize
py main.py --validate
py main.py --walk-forward
```

## Phase 4: initialize paper tracking once

After merging Phase 4 and downloading the updated repository:

```powershell
py main.py --paper-init
```

Initialization:

- locks the stable configuration selected by repeated validation
- starts after the latest completed trading day
- does not backfill optimized historical trades
- creates a persistent local paper-tracking folder

Locked configuration:

- minimum score: 80
- minimum ADX: 30
- minimum RVOL: 1.0
- stop: 1.5 ATR
- target: 2.5R
- long only

## Update after a completed market day

```powershell
py main.py --paper-update
```

Run this after the normal market session has completed. The tracker:

- processes only new completed days
- prevents duplicate trades
- carries simulated capital forward
- closes positions by the end of each day
- keeps the configuration locked
- never places an order

## Phase 4 outputs

Files are saved under `output\QQQ\paper`:

- `paper_state.json` — locked settings and processing checkpoint
- `paper_trades.csv` — every new paper trade
- `paper_summary.json` — progress, metrics, and final PASS/FAIL

The status remains `COLLECTING` until at least 20 paper trades are recorded. It then requires:

- positive net profit
- positive average R
- profit factor of at least 1.20
- maximum drawdown no worse than 5%

Keep the entire `output\QQQ\paper` folder. Deleting it resets the paper test.

## Important

This is end-of-day research tracking, not a real-time alert or execution system. A PASS is still not a guarantee of future performance.
