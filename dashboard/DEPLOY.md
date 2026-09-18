# MnT Dashboard deployment

The dashboard is a FastAPI service intended to run on the Kronos VM. It combines Alpaca market data, Kronos forecasts, MnT Fusion scoring, optional Unusual Whales Gamma/options-flow context, SQLite signal/outcome learning, actual option-contract shadow marks, a READY-alert shadow journal, a browser Learning Lab, and an unattended Discord alert worker.

## 1. Install and configure

The safest deployment path is:

```bash
cd ~/Hanif-Trading-Suite-Pro/dashboard
chmod +x deploy_mnt.sh
./deploy_mnt.sh
```

The deployment script uses the existing `/home/airomair/kronos-venv`, protects against a dirty git working tree, installs dependencies, validates Python modules, installs/restarts the systemd units, waits for dashboard health, runs the preflight, starts the alert supervisor, waits for its heartbeat, and prints the final MnT status.

Shared Alpaca/Kronos credentials remain in:

```text
/home/airomair/Kronos/.env
```

MnT-specific overrides live separately in:

```text
/home/airomair/Hanif-Trading-Suite-Pro/dashboard/mnt.env
```

Create the override once from the safe MnT-only template:

```bash
cd ~/Hanif-Trading-Suite-Pro/dashboard
cp -n mnt.env.example mnt.env
chmod 600 mnt.env
```

Do **not** duplicate `ALPACA_API_KEY`, `ALPACA_SECRET_KEY`, or other shared credentials in `mnt.env`. Both systemd services load the shared Kronos environment first and MnT-only overrides second. The deployment script does not `source` either credential file as shell code.

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
curl "http://127.0.0.1:8080/api/radar?limit=3"
curl http://127.0.0.1:8080/api/kronos/market-regime
curl "http://127.0.0.1:8080/api/kronos/signals?limit=5"
```

A live Fusion research check can be run with:

```bash
curl -sS -X POST \
  "http://127.0.0.1:8080/api/kronos/fusion/SPY?max_contract_cost=300" | \
  python -m json.tool
```

Important fields:

- `fusion_score.score` — MnT setup-quality score.
- `fusion_score.coverage_pct` — percentage of scoring weight backed by available data.
- `fusion_score.missing_layers` — layers omitted and reweighted.
- `gamma` / `flow` — professional-data context or explicit unavailable status.
- `execution_gate` — server-side review gate including no-chase state.
- `signal_id` — persisted learning ID.
- `calibration_refresh` — older pending signals evaluated against later 5-minute bars.

## 3. Deployment preflight

With the dashboard running:

```bash
cd ~/Hanif-Trading-Suite-Pro/dashboard
source ~/kronos-venv/bin/activate
python mnt_preflight.py
```

`READY_FOR_SHADOW_SESSION` means infrastructure/configuration checks passed. It does **not** validate profitability and does not authorize an order.

The preflight checks Alpaca configuration, dashboard/Kronos connectivity, Market Radar, signal-history API access, and writable signal/shadow/state paths. Missing Discord or Unusual Whales configuration is a warning rather than a silent failure.

## 4. Signal learning and calibration

Each Fusion response is persisted when `MNT_SIGNAL_DB_ENABLED=true`. Later analyses evaluate older signals once sufficient future 5-minute bars exist.

MnT records:

- 1-hour and 2-hour directional returns.
- MFE / MAE.
- target-first versus stop-first outcome.
- ambiguous same-bar target/stop events rather than guessing order.

Review calibration:

```bash
curl "http://127.0.0.1:8080/api/kronos/signals/calibration?symbol=SPY&limit=500" | python -m json.tool
python calibration_report.py --symbol SPY
python calibration_report.py
```

The full report includes:

- score-bucket outcomes.
- advisory stricter-threshold recommendations.
- per-layer effectiveness for technical, Kronos, Gamma, flow, market, contract, and momentum layers.
- READY-alert shadow outcomes.
- actual option-contract shadow returns.
- chronological Fusion-weight challenger results.

### Weight challenger

`weight_challenger.py` does **not** rewrite the live Fusion weights. It trains small candidate-weight changes on older resolved signals, then validates them only against later unseen signals.

A candidate is rejected if it improves apparent win rate mainly by collapsing the number of qualifying opportunities. By default, the candidate must retain at least 70% of the baseline holdout setup count and clear the configured holdout improvement threshold.

Useful safeguards live in `mnt.env`:

```dotenv
MNT_WEIGHT_CHALLENGER_TRAIN_FRACTION=0.70
MNT_WEIGHT_CHALLENGER_MIN_RESOLVED=40
MNT_WEIGHT_CHALLENGER_MIN_HOLDOUT=12
MNT_WEIGHT_CHALLENGER_MIN_SELECTED=8
MNT_WEIGHT_CHALLENGER_MIN_LAYER_LIFT=8
MNT_WEIGHT_CHALLENGER_MIN_HOLDOUT_IMPROVEMENT=3
```

## 5. READY journal and actual option-contract marks

A READY candidate that survives the same ranking/cap policy used for Discord is written to `mnt_shadow_trades.sqlite3`. This journal stores what MnT actually surfaced: underlying price, entry range, stop, target, first option candidate, score, coverage, and originating `signal_id`.

For options, MnT measures shadow performance using the deliberately conservative convention:

```text
entry = surfaced ask
later value = later bid
```

This includes bid/ask friction instead of flattering results with midpoint-to-midpoint math.

Marks are collected at nominal 15 / 30 / 60 / 120-minute horizons when a usable quote is available. The database stores both:

- when the collector ran; and
- the quote timestamp supplied by the market-data source.

Calibration prefers the **source quote timestamp** when deciding whether a mark was actually close enough to the requested horizon. A stale closing quote fetched later is stored for auditability but excluded from normal performance summaries if its timing error is too large.

Configure timing tolerance with:

```dotenv
MNT_OPTION_MARK_MAX_LAG_MINUTES=10
```

Late-day setups may legitimately have no 60/120-minute mark because the options market closed before that horizon. Missing evidence is preferable to inventing a stale observation.

## 6. Daily shadow scorecard

Print a single ET-session scorecard from the command line:

```bash
python daily_scorecard.py
python daily_scorecard.py --date 2026-09-17
```

It reports:

- READY ideas and Discord deliveries.
- long/short mix.
- resolved underlying target-first win/loss results.
- selected option-horizon average/median and positive rate.
- large gains/losses.
- best and worst measured option idea.
- a `STRONG`, `MIXED`, `WEAK`, or `COLLECTING` quality state.
- conservative next-session guidance that never loosens gates from one strong day.

The Learning Lab uses `MNT_DAILY_SCORECARD_OPTION_HORIZON=60` by default.

## 7. Learning Lab

The dashboard now includes an **MnT Learning Lab** underneath the main trading workspace. The supervisor writes a browser-safe aggregate snapshot to:

```text
dashboard/static/mnt-runtime.json
```

The snapshot excludes environment values, credentials, raw signal payloads, and brokerage authorization data.

The Learning Lab refreshes every 30 seconds and shows:

- today’s shadow quality state.
- aggregate signal target-first win rate.
- READY-alert outcome rate.
- current versus advisory score threshold.
- chronological weight-challenger status.
- actual option-contract returns at 15 / 30 / 60 / 120 minutes.
- worker health and current shortlist.
- session-risk state and next-session note.

Treat all of these as **evidence collection**, not proof of a future edge.

## 8. Unattended Discord workflow

The supervisor uses a two-stage scan:

1. `/api/radar` cheaply ranks the configured universe.
2. only a bounded long/short shortlist receives full Kronos + Gamma + flow + market + option analysis.
3. Fusion candidates are ranked before Discord delivery.

Lifecycle messages:

- **PRE-TRIGGER** — quality is building, but confirmation is incomplete. This is intentionally early.
- **READY** — the server-side `execution_gate` permits entry review. This still does not authorize/place an order.
- **STAND DOWN** — an earlier PRE-TRIGGER weakened, rejected, or became no-chase.

Recent PRE-TRIGGER symbols remain sticky until resolved. Old alert state expires so prior-day ideas cannot suppress a fresh setup.

## 9. Session risk governor

The session governor is based on MnT’s shadow evidence, **not brokerage P/L**. It watches things such as READY-idea count and consecutive poor option marks.

It is advisory by default:

```dotenv
MNT_SESSION_RISK_ENFORCE=false
```

If later enabled intentionally, a tripped governor pauses new alert delivery while existing shadow ideas continue to receive eligible option marks.

Stale source quotes cannot trigger the option-loss streak breaker. Configure the accepted timing error separately:

```dotenv
MNT_SESSION_MAX_MARK_TIMING_ERROR_MINUTES=10
```

`RISK_PAUSED` is considered an intentional operational state rather than a dead worker.

## 10. Optional end-of-session Discord scorecard

A once-per-ET-session Discord summary is implemented but **disabled by default** so enabling the worker cannot unexpectedly add another message type.

To enable it:

```dotenv
MNT_EOD_SCORECARD_ENABLED=true
MNT_EOD_SCORECARD_HOUR_ET=16
MNT_EOD_SCORECARD_MINUTE_ET=15
```

The supervisor checks this even after the normal intraday scan window has closed. A persistent state file ensures only one scorecard is sent for a given ET session date.

The scorecard includes session quality, READY count, stock target-first results, measured option return statistics, best/worst idea, and the next-session note. It is explicitly labeled shadow/research-only.

## 11. Systemd services

Install manually if not using `deploy_mnt.sh`:

```bash
sudo cp hanif-dashboard.service /etc/systemd/system/hanif-dashboard.service
sudo cp mnt-alert-worker.service /etc/systemd/system/mnt-alert-worker.service
sudo systemctl daemon-reload
sudo systemctl enable --now hanif-dashboard mnt-alert-worker
```

Useful commands:

```bash
sudo systemctl status hanif-dashboard --no-pager
sudo systemctl status mnt-alert-worker --no-pager
journalctl -u hanif-dashboard -n 100 --no-pager
journalctl -u mnt-alert-worker -f
```

The alert-worker unit runs `mnt_alert_supervisor.py` using the same Kronos virtualenv Python as the dashboard.

## 12. One-command operational status

```bash
cd ~/Hanif-Trading-Suite-Pro/dashboard
source ~/kronos-venv/bin/activate
python mnt_status.py
```

The status report includes:

- `overall`: `OK`, `DEGRADED`, `ATTENTION`, or an unknown state.
- worker/session state and heartbeat age.
- stale heartbeat detection.
- session-risk state.
- radar shortlist and sticky PRE-TRIGGERs.
- Fusion success/error counts.
- alert delivery/suppression counts.
- option-mark collector status.
- EOD scorecard delivery status.
- READY shadow results.

## 13. Cloudflare

Published application route:

- Hostname: `dashboard.mntlogic.com`
- Service URL: `http://localhost:8080`

Use Cloudflare Access before treating the published hostname as private.

## Current safety boundary

MnT now includes market discovery, Fusion analysis, coverage-aware scoring, opening/no-chase gates, option candidate review, optional Gamma/flow context, persistent signal calibration, layer attribution, advisory threshold policy, chronological weight challenges, actual option-contract shadow marks, session scorecards, two-stage unattended scanning, PRE-TRIGGER/READY/STAND DOWN lifecycle alerts, stale-state expiration, session-risk governance, worker health/status, deployment preflight, Learning Lab visualization, and an optional EOD Discord scorecard.

It **does not place brokerage orders** in this branch. `READY` means “review entry conditions now,” not “trade automatically.” Allow the learning stores to accumulate meaningful samples before changing live thresholds, weights, or enforcement rules.
