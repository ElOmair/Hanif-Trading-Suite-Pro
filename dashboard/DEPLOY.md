# Dashboard deployment

The dashboard is a separate FastAPI service intended to run on the Kronos VM and reuse the existing Alpaca environment variables.

## First test

```bash
cd ~/Hanif-Trading-Suite-Pro/dashboard
source ~/kronos-venv/bin/activate
pip install -r requirements.txt
uvicorn app:app --host 127.0.0.1 --port 8080
```

In another terminal:

```bash
curl http://127.0.0.1:8080/api/health
```

## Service

After the manual test succeeds:

```bash
sudo cp hanif-dashboard.service /etc/systemd/system/hanif-dashboard.service
sudo systemctl daemon-reload
sudo systemctl enable --now hanif-dashboard
sudo systemctl status hanif-dashboard --no-pager
```

The provided service reads Alpaca variables from `/home/airomair/Kronos/.env` and checks Kronos at `http://127.0.0.1:8000`.

## Cloudflare

Add a published application route on the existing named tunnel:

- Hostname: `dashboard.mntlogic.com`
- Service URL: `http://localhost:8080`

Use Cloudflare Access on the dashboard hostname before treating the site as private.

## Current scope

Phase 1 includes Alpaca candlesticks, quote updates, a fast technical Market Radar, and Kronos health. Deep Kronos analysis, option-fit details, risk gates, and background portfolio synchronization are intentionally separate follow-on integrations.
