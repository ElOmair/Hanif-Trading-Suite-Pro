# MnT Dashboard deployment

The dashboard is a FastAPI service intended to run on the Kronos VM. It combines Alpaca market data, Kronos forecasts, MnT Fusion scoring, optional Unusual Whales Gamma/options-flow context, and a local SQLite signal-history/calibration store.

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

These statistics are descriptive historical calibration, not a guarantee of future performance.

## 4. systemd service

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

## 5. Cloudflare

Add a published application route on the existing named tunnel:

- Hostname: `dashboard.mntlogic.com`
- Service URL: `http://localhost:8080`

Use Cloudflare Access on the dashboard hostname before treating the site as private.

## Current scope

MnT now includes candlesticks/quotes, Market Radar, Kronos Fusion analysis, coverage-aware scoring, opening/no-chase gates, option candidate review, optional Gamma and options-flow context, beginner explanations, persistent signal history, and automatic 1h/2h signal calibration.

The calibration database should be allowed to accumulate enough observations before changing score thresholds based on apparent win rates. Avoid tuning to a small sample of recent trades.
