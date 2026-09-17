# MnT Schwab / thinkorswim API setup

MnT integrates with the current Charles Schwab Trader API and Market Data API used for Schwab/thinkorswim retail brokerage access.

## What Phase 1 enables

- OAuth connection to the Schwab account(s) you approve.
- masked account balances and positions in MnT.
- Schwab quotes.
- Schwab option chains.
- MnT-normalized option candidates ranked for cost, spread, open interest, volume, delta, DTE, and extreme IV.
- automatic short-lived access-token refresh.
- visible reauthorization state for the approximately seven-day refresh-token window.

Phase 1 does **not** expose an order submission, replace, or cancel endpoint.

## 1. Schwab Developer Portal

In the Schwab developer application that has Trader API access, configure the callback URL to exactly match:

```text
https://dashboard.mntlogic.com/api/schwab/callback
```

The callback must be HTTPS. If you use a different hostname, update both the Schwab app registration and `SCHWAB_CALLBACK_URL` so they match exactly.

Make sure the app is approved for the Trader API / Market Data capabilities you intend to use.

## 2. Configure MnT on Kronos

Do not put credentials in GitHub and do not paste the app secret into chat.

Edit the MnT-only server environment file:

```bash
cd /home/airomair/Hanif-Trading-Suite-Pro/dashboard
nano mnt.env
```

Set:

```dotenv
MNT_SCHWAB_ENABLED=true
SCHWAB_APP_KEY=<your Schwab app key>
SCHWAB_APP_SECRET=<your Schwab app secret>
SCHWAB_CALLBACK_URL=https://dashboard.mntlogic.com/api/schwab/callback
MNT_SCHWAB_ORDER_SUBMISSION_ENABLED=false
```

Optional token/state locations:

```dotenv
SCHWAB_TOKEN_FILE=/home/airomair/mnt-data/schwab_tokens.json
SCHWAB_OAUTH_STATE_FILE=/home/airomair/mnt-data/schwab_oauth_state.json
```

The token and OAuth-state files are server-side only and are written with private-file permissions where supported.

## 3. Deploy/restart

After the branch is deployed:

```bash
cd /home/airomair/Hanif-Trading-Suite-Pro/dashboard
./deploy_mnt.sh
```

The dashboard service starts `app_schwab:app`, which retains the existing dashboard and mounts the Schwab routes.

On the **first** deployment, preflight may report `schwab_authorization` as a warning because no OAuth token exists yet. That warning intentionally does not block deployment: the dashboard has to be online before you can open `/broker` and complete the interactive authorization flow.

A Phase 1 deployment **will** fail preflight if `MNT_SCHWAB_ORDER_SUBMISSION_ENABLED=true`. Keep it false.

## 4. Authorize the Schwab account

Open:

```text
https://dashboard.mntlogic.com/broker
```

Select **Connect Schwab** and complete the Schwab login/consent flow. MnT validates the OAuth state before exchanging the one-time authorization code.

After success, the broker page should show `CONNECTED` and display only masked account identifiers.

Then rerun preflight if desired:

```bash
cd /home/airomair/Hanif-Trading-Suite-Pro/dashboard
source /home/airomair/kronos-venv/bin/activate
python mnt_preflight.py
```

The Schwab authorization check should now be green instead of a warning.

## 5. Validate from the Kronos shell

```bash
curl -sS http://127.0.0.1:8080/api/schwab/status | python -m json.tool
curl -sS http://127.0.0.1:8080/api/schwab/positions | python -m json.tool
curl -sS 'http://127.0.0.1:8080/api/schwab/quotes?symbols=SPY,QQQ' | python -m json.tool
curl -sS 'http://127.0.0.1:8080/api/schwab/options/SPY/candidates?direction=LONG&style=swing&max_contract_cost=300&limit=5' | python -m json.tool
```

The status endpoint intentionally does not return access tokens, refresh tokens, the client secret, raw account numbers, or account hashes. It also reports `order_submission_enabled: false` throughout Phase 1.

## 6. Token behavior

Schwab access tokens are short-lived, so MnT refreshes them automatically using the stored refresh token.

The refresh-token authorization window is treated separately. Access-token refreshes do not restart the reauthorization clock. When reauthorization is due, `/api/schwab/status` reports it and the broker page prompts for a new interactive Schwab connection.

## 7. Cloudflare Access note

If the Schwab redirect reaches the Cloudflare Access login page instead of `/api/schwab/callback`, the browser cannot complete the OAuth exchange. Prefer keeping the user authenticated to the dashboard during the connection flow. If a policy change is necessary, limit any exception to the callback path rather than making the full dashboard public.

## Current safety boundary

`MNT_SCHWAB_ORDER_SUBMISSION_ENABLED=false` remains the required Phase 1 setting. The browser page and API intentionally expose no order-placement route. Order staging/execution should be implemented as a separate phase with explicit account selection, max-risk controls, review/approval state, idempotency, and kill-switch behavior.
