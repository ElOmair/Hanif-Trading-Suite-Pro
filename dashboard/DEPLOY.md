# MnT Dashboard deployment

The dashboard is a FastAPI service intended to run on the Kronos VM. It combines Alpaca market data, Kronos forecasts, MnT Fusion scoring, optional Unusual Whales Gamma/options-flow context, a local SQLite signal-history/calibration store, and an optional unattended Discord alert worker.

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

## 3. Signal learning / calibration

Each Fusion response is saved locally when `MNT_SIGNAL_DB_ENABLED=true`. On later analyses of that symbol, MnT evaluates older pending signals once enough future 5-minute bars exist.

It records 1-hour/2-hour directional return, MFE/MAE, and whether Target 1 or the stop was reached first. Same-bar target/stop events are marked ambiguous instead of guessed.

Review calibration history with:

```bash
curl "http://127.0.0.1:8080/api/kronos/signals/calibration?symbol=SPY&limit=500" | \
  python -m json.tool
```

Generate a shadow threshold report without changing any live gates:

```bash
cd ~/Hanif-Trading-Suite-Pro/dashboard
source ~/kronos-venv/bin/activate
python calibration_report.py --symbol SPY
python calibration_report.py
```

`MNT_CALIBRATION_MIN_RESOLVED` controls how many resolved WIN/LOSS observations are required before MnT will even recommend a threshold change. `MNT_CALIBRATION_TARGET_WIN_RATE` sets the descriptive target-first win-rate objective. The policy is advisory only and never relaxes or edits the live risk governor automatically.

These statistics are descriptive historical calibration, not a guarantee of future performance.

## 4. Dashboard systemd service

After the manual test succeeds:

```bash
sudo cp hanif-dashboard.service /etc/systemd/system/hanif-dashboard.service
sudo systemctl daemon-reload
sudo systemctl enable --now hanif-dashboard
sudo systemctl status hanif-dashboard --no-pager
```

The provided service should run as the Kronos user and keep all market-data credentials server-side. If you keep the environment file somewhere other than the service's configured path, update the unit before enabling it.

Useful operations:

```bash
sudo systemctl restart hanif-dashboard
journalctl -u hanif-dashboard -n 100 --no-pager
journalctl -u hanif-dashboard -f
```

## 5. Unattended Discord alerts

The optional `mnt_alert_worker.py` scans a configured symbol list during the market session and calls the dashboard Fusion endpoint. It supports two useful alert stages:

- **PRE-TRIGGER** — score and coverage are strong enough to pay attention, but the Decision Engine has not confirmed yet. This is intentionally early so Discord does not first alert after the entry has already run.
- **READY** — the server-side `execution_gate` allows entry review. The worker still does not place or authorize an order.

Configure the worker in `.env`:

```dotenv
MNT_DASHBOARD_API_URL=http://127.0.0.1:8080
MNT_DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...
MNT_ALERT_SYMBOLS=SPY,QQQ,NVDA,TSLA,AAPL,AMD,META,AMZN,MSFT,GOOGL,PLTR,COIN
MNT_ALERT_SCAN_SECONDS=60
MNT_PRETRIGGER_SCORE=72
MNT_PRETRIGGER_COVERAGE=55
MNT_ALERT_COOLDOWN_SECONDS=900
MNT_MAX_CONTRACT_COST=300
```

Manual smoke test:

```bash
cd ~/Hanif-Trading-Suite-Pro/dashboard
source ~/kronos-venv/bin/activate
python mnt_alert_worker.py
```

Install it as a service after the dashboard itself is healthy:

```bash
sudo cp mnt-alert-worker.service /etc/systemd/system/mnt-alert-worker.service
sudo systemctl daemon-reload
sudo systemctl enable --now mnt-alert-worker
sudo systemctl status mnt-alert-worker --no-pager
journalctl -u mnt-alert-worker -f
```

The worker stores a small local alert-state file so repeated scans do not spam the same PRE-TRIGGER setup. A transition from PRE-TRIGGER to READY is allowed to alert immediately.

## 6. Cloudflare

Add a published application route on the existing named tunnel:

- Hostname: `dashboard.mntlogic.com`
- Service URL: `http://localhost:8080`

Use Cloudflare Access on the dashboard hostname before treating the site as private.

## Current scope

MnT now includes candlesticks/quotes, Market Radar, Kronos Fusion analysis, coverage-aware scoring, opening/no-chase gates, option candidate review, optional Gamma and options-flow context, beginner explanations, persistent signal history, automatic 1h/2h signal calibration, shadow threshold recommendations, and unattended pre-trigger/ready Discord alerts.

The calibration database should be allowed to accumulate enough observations before changing score thresholds based on apparent win rates. Avoid tuning to a small sample of recent trades.
