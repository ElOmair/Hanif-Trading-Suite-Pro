# Hanif Trading Suite Pro — Phase 2

## Run baseline
```powershell
python main.py
```

## Run optimizer
```powershell
python main.py --optimize
```

The optimizer tests 1,728 configurations and may take several minutes.

## Main outputs in output\QQQ
- metrics.json
- trades.csv
- equity_curve.png
- diagnostic_by_direction.csv
- diagnostic_by_setup.csv
- diagnostic_by_hour.csv
- diagnostic_by_score.csv
- diagnostic_by_adx.csv
- diagnostic_by_rvol.csv
- parameter_sweep.csv
- top_25_configurations.csv

Upload `top_25_configurations.csv` after the optimizer finishes.

This is research software, not an order execution system. Optimized results can be overfit and require out-of-sample and paper-trading validation.
