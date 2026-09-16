# MnT Dashboard deployment

The dashboard is a FastAPI service intended to run on the Kronos VM. It combines Alpaca market data, Kronos forecasts, MnT Fusion scoring, optional Unusual Whales Gamma/options-flow context, SQLite signal/outcome learning, a READY-alert shadow journal, and an unattended Discord alert worker.

## 1. Install and configure

```bash
cd ~/Hanif-Trading-Suite-Pro/dashboard
source ~/kronos-venv/bin/activate
pip install -r requirements.txt
cp -n .env.example .env
```

Edit `dashboard/.env` and configure at minimum the Alpaca credentials and Kronos URL. Optional professional-data layers use server-side credentials only:

```dotenv
ALPACA_API_KEY=...
ALPACA_SECRET_KEY=...
ALPACA_DATA_FEED=iex
KRONOS_API_URL=http://127.0.0.1:8000

MNT_GAMMA_PROVIDER=auto
MNT_FLOW_PROVIDER=auto
UNUSUAL_WHALES_API_TOKEN=...

MNT_SIGNAL_DB_ENABLED=true
MNT_SHADOW_TRADES_ENABLED=true
MNT_BAR_TIMEZONE=America/New_York
```

The Unusual Whales ChatGPT connector does not automatically supply credentials to this standalone service. If no deployable API token is configured, MnT marks Gamma/flow unavailable and reweights the Fusion score rather than silently counting missing data as zero.

## 2. First manual test

```bash
cd ~/Hanif-Trading-Suite-Pro/dashboard
source ~/kronos-venv/bin/activate
uvicorn app:app --host 127.0.0.1 --port 8080
```

In another terminal:

```bash
curl http://127.0.0.1:8080/api/health
curl http://127.0.0.1:8080/api/system
curl http://127.0.0.1:8080/api/radar?limit=3
curl http://127.0.0.1:8080/api/kronos/market-regime
curl "http://127.0.0.1:8080/api/kronos/signals?limit=5"
```

A live Fusion check can be run with:

```bash
curl -sS -X POST \
  "http://127.0.0.1:8080/api/kronos/fusion/SPY?max_contract_cost=300" | \
  python -m json.tool
```

Important fields to verify are:

- `fusion_score.score` — MnT setup-quality score.
- `fusion_score.coverage_pct` — percentage of scoring weight backed by available data.
- `fusion_score.missing_layers` — data layers omitted and reweighted.
- `gamma` and `flow` — provider status and professional-data context.
- `execution_gate` — server-side entry-review gate, including no-chase state.
- `signal_id` — persisted signal-history ID.
- `calibration_refresh` — older signals evaluated against refreshed 5-minute history.

## 3. Run the deployment preflight

With the dashboard running and `.env` populated:

```bash
cd ~/Hanif-Trading-Suite-Pro/dashboard
source ~/kronos-venv/bin/activate
python mnt_preflight.py
```

The command exits non-zero if a required check fails. It verifies Alpaca configuration, dashboard/Kronos connectivity, Market Radar, signal-history API access, and writable local data paths. Missing Discord or Unusual Whales configuration is reported as a warning rather than silently ignored.

`READY_FOR_SHADOW_SESSION` means infrastructure/configuration checks passed. It does **not** mean the trading model is profitable or that orders are authorized.

## 4. Signal learning / calibration

Each Fusion response is saved locally when `MNT_SIGNAL_DB_ENABLED=true`. On later analyses of that symbol, MnT evaluates older pending signals once enough future 5-minute bars exist.

It records 1-hour/2-hour directional return, MFE/MAE, and whether Target 1 or the stop was reached first. Same-bar target/stop events are marked ambiguous instead of guessed.

Review calibration history with:

```bash
curl "http://127.0.0.1:8080/api/kronos/signals/calibration?symbol=SPY&limit=500" | \
  python -m json.tool
```

Generate the full learning report:

```bash
cd ~/Hanif-Trading-Suite-Pro/dashboard
source ~/kronos-venv/bin/activate
python calibration_report.py --symbol SPY
python calibration_report.py
```

The report includes score-bucket outcome calibration, shadow-mode threshold recommendations, per-layer effectiveness, and READY-alert shadow-trade results linked to the exact persisted Fusion signals.

`MNT_CALIBRATION_MIN_RESOLVED` controls how many resolved WIN/LOSS observations are required before MnT will even recommend a threshold change. `MNT_CALIBRATION_TARGET_WIN_RATE` sets the descriptive target-first win-rate objective. The policy is advisory only and never relaxes or edits the live risk governor automatically. Layer-effectiveness output is correlation, not proof of causation, and does not auto-edit Fusion weights.

These statistics are descriptive historical calibration, not a guarantee of future performance.

## 5. Dashboard systemd service

After the manual test succeeds:

```bash
sudo cp hanif-dashboard.service /etc/systemd/system/hanif-dashboard.service
sudo systemctl daemon-reload
sudo systemctl enable --now hanif-dashboard
sudo systemctl status hanif-dashboard --no-pager
```

Useful operations:

```bash
sudo systemctl restart hanif-dashboard
journalctl -u hanif-dashboard -n 100 --no-pager
journalctl -u hanif-dashboard -f
```

## 6. Unattended Discord alerts

The worker uses a two-stage scan so expensive Kronos Fusion analysis stays timely:

1. `/api/radar` cheaply ranks the configured market universe.
2. only the strongest long/short shortlist receives full Kronos + Gamma + flow + market + option analysis.
3. Fusion candidates are ranked before Discord delivery.

The worker supports three lifecycle messages:

- **PRE-TRIGGER** — score and coverage are strong enough to pay attention, but confirmation is incomplete.
- **READY** — the server-side `execution_gate` allows entry review. A READY idea that survives ranking is also written to the shadow journal even if Discord is unavailable.
- **STAND DOWN** — an earlier PRE-TRIGGER weakened, was rejected, or became a no-chase.

Recent PRE-TRIGGER names remain sticky in the Fusion shortlist until they resolve, even if they fall off the fast radar. Old alert state expires so a previous-day setup cannot suppress a fresh signal.

Configure the worker in `.env`:

```dotenv
MNT_DASHBOARD_API_URL=http://127.0.0.1:8080
MNT_DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...
MNT_ALERT_SYMBOLS=SPY,QQQ,NVDA,TSLA,AAPL,AMD,META,AMZN,MSFT,GOOGL,PLTR,COIN
MNT_ALERT_SCAN_SECONDS=60
MNT_FUSION_SHORTLIST=4
MNT_STICKY_PRETRIGGER_LIMIT=2
MNT_PRETRIGGER_SCORE=72
MNT_PRETRIGGER_COVERAGE=55
MNT_ALERT_COOLDOWN_SECONDS=900
MNT_ALERT_STATE_MAX_AGE_SECONDS=14400
MNT_MAX_PRETRIGGER_ALERTS_PER_SCAN=3
MNT_MAX_READY_ALERTS_PER_SCAN=5
MNT_MAX_CONTRACT_COST=300
MNT_WORKER_STALE_SECONDS=180
```

For a manual foreground run with the same heartbeat behavior used by systemd:

```bash
cd ~/Hanif-Trading-Suite-Pro/dashboard
source ~/kronos-venv/bin/activate
python mnt_alert_supervisor.py
```

Install it as a service after the dashboard itself is healthy:

```bash
sudo cp mnt-alert-worker.service /etc/systemd/system/mnt-alert-worker.service
sudo systemctl daemon-reload
sudo systemctl enable --now mnt-alert-worker
sudo systemctl status mnt-alert-worker --no-pager
journalctl -u mnt-alert-worker -f
```

The systemd unit launches `mnt_alert_supervisor.py`, which wraps the established scanner and atomically writes `mnt_worker_status.json` after every scan and during off-hours.

The worker does not place a brokerage order. READY means “review entry conditions now,” not “order sent.”

## 7. One-command operational status

Once the worker is running, use:

```bash
cd ~/Hanif-Trading-Suite-Pro/dashboard
source ~/kronos-venv/bin/activate
python mnt_status.py
```

The status report shows:

- `overall`: `OK`, `DEGRADED`, or `ATTENTION`.
- worker/session state and heartbeat age.
- whether the heartbeat is stale.
- last radar shortlist and sticky PRE-TRIGGER names.
- Fusion attempts/successes/errors.
- PRE-TRIGGER/READY candidates, Discord sends, STAND DOWN sends, and rank suppression.
- READY shadow records written on the last scan.
- aggregate READY-alert shadow results.

By default a heartbeat older than 180 seconds is treated as stale. Override with `MNT_WORKER_STALE_SECONDS` if needed.

## 8. Shadow READY journal

The separate `mnt_shadow_trades.sqlite3` journal records READY ideas that survive the same ranking/cap policy used by Discord. It stores the underlying price, planned entry/stop/target, first option candidate, score, coverage, and the originating `signal_id`.

Because it links back to the normal signal outcome store, the calibration report can answer “how did the alerts we actually surfaced perform?” without mixing those observations with the older Phase 2 backtest strategy.

This is still shadow testing. No live or paper brokerage order is sent by the journal.

## 9. Cloudflare

Add a published application route on the existing named tunnel:

- Hostname: `dashboard.mntlogic.com`
- Service URL: `http://localhost:8080`

Use Cloudflare Access on the dashboard hostname before treating the site as private.

## Current scope

MnT now includes candlesticks/quotes, Market Radar, Kronos Fusion analysis, coverage-aware scoring, opening/no-chase gates, option candidate review, optional Gamma and options-flow context, beginner explanations, persistent signal history, automatic 1h/2h signal calibration, layer attribution, shadow threshold recommendations, two-stage unattended scanning, ranked PRE-TRIGGER/READY Discord alerts, STAND DOWN lifecycle messages, stale-state expiration, a READY shadow journal, deployment preflight, and worker heartbeat/status reporting.

The calibration databases should be allowed to accumulate enough observations before changing score thresholds or model weights. Avoid tuning to a small sample of recent trades.
