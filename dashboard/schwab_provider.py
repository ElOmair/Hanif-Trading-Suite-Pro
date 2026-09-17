from __future__ import annotations

import base64
import json
import os
import secrets
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import httpx

ROOT = Path(__file__).resolve().parent
AUTH_BASE = "https://api.schwabapi.com/v1/oauth"
TRADER_BASE = "https://api.schwabapi.com/trader/v1"
MARKET_BASE = "https://api.schwabapi.com/marketdata/v1"
DEFAULT_TOKEN_PATH = ROOT / "data" / "schwab_tokens.json"
DEFAULT_STATE_PATH = ROOT / "data" / "schwab_oauth_state.json"


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def token_path() -> Path:
    return Path(os.getenv("SCHWAB_TOKEN_FILE", str(DEFAULT_TOKEN_PATH))).expanduser()


def oauth_state_path() -> Path:
    return Path(os.getenv("SCHWAB_OAUTH_STATE_FILE", str(DEFAULT_STATE_PATH))).expanduser()


def configured() -> bool:
    return bool(
        _env_bool("MNT_SCHWAB_ENABLED", False)
        and os.getenv("SCHWAB_APP_KEY", "").strip()
        and os.getenv("SCHWAB_APP_SECRET", "").strip()
        and os.getenv("SCHWAB_CALLBACK_URL", "").strip()
    )


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _epoch_now() -> float:
    return time.time()


def _write_private_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    try:
        os.chmod(temp, 0o600)
    except OSError:
        pass
    temp.replace(path)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def token_status() -> dict[str, Any]:
    payload = _read_json(token_path())
    access_expires_at = float(payload.get("access_expires_at") or 0)
    refresh_expires_at = float(payload.get("refresh_expires_at") or 0)
    now = _epoch_now()
    has_refresh = bool(payload.get("refresh_token"))
    return {
        "configured": configured(),
        "authorized": bool(payload.get("access_token") or has_refresh),
        "access_token_valid": bool(payload.get("access_token")) and access_expires_at > now + 30,
        "refresh_token_valid": has_refresh and refresh_expires_at > now + 60,
        "access_expires_at": datetime.fromtimestamp(access_expires_at, tz=timezone.utc).isoformat() if access_expires_at else None,
        "refresh_expires_at": datetime.fromtimestamp(refresh_expires_at, tz=timezone.utc).isoformat() if refresh_expires_at else None,
        "reauthorization_required": configured() and (not has_refresh or refresh_expires_at <= now + 60),
        "order_submission_enabled": _env_bool("MNT_SCHWAB_ORDER_SUBMISSION_ENABLED", False),
        "research_only": not _env_bool("MNT_SCHWAB_ORDER_SUBMISSION_ENABLED", False),
    }


def begin_oauth() -> str:
    if not configured():
        raise RuntimeError("Schwab integration is not configured")
    state = secrets.token_urlsafe(32)
    _write_private_json(
        oauth_state_path(),
        {"state": state, "created_at": _utc_now().isoformat(), "created_epoch": _epoch_now()},
    )
    params = {
        "client_id": os.environ["SCHWAB_APP_KEY"].strip(),
        "redirect_uri": os.environ["SCHWAB_CALLBACK_URL"].strip(),
        "response_type": "code",
        "state": state,
    }
    return f"{AUTH_BASE}/authorize?{urlencode(params)}"


def _validate_state(state: str | None) -> None:
    expected = _read_json(oauth_state_path())
    created = float(expected.get("created_epoch") or 0)
    if not state or state != expected.get("state"):
        raise RuntimeError("OAuth state did not match")
    if not created or _epoch_now() - created > 600:
        raise RuntimeError("OAuth state expired; restart Schwab authorization")


def _basic_auth_header() -> str:
    raw = f"{os.environ['SCHWAB_APP_KEY'].strip()}:{os.environ['SCHWAB_APP_SECRET'].strip()}".encode("utf-8")
    return "Basic " + base64.b64encode(raw).decode("ascii")


async def exchange_code(code: str, state: str | None = None) -> dict[str, Any]:
    if not configured():
        raise RuntimeError("Schwab integration is not configured")
    _validate_state(state)
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.post(
            f"{AUTH_BASE}/token",
            headers={
                "Authorization": _basic_auth_header(),
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": os.environ["SCHWAB_CALLBACK_URL"].strip(),
            },
        )
        response.raise_for_status()
        payload = response.json()
    _store_tokens(payload, initial=True)
    try:
        oauth_state_path().unlink(missing_ok=True)
    except OSError:
        pass
    return token_status()


def _store_tokens(payload: dict[str, Any], *, initial: bool) -> None:
    previous = _read_json(token_path())
    now = _epoch_now()
    refresh = payload.get("refresh_token") or previous.get("refresh_token")
    refresh_expires_at = previous.get("refresh_expires_at")
    if initial or payload.get("refresh_token"):
        # Schwab Trader API refresh tokens are short-lived. Keep the issue time so
        # the UI can warn before the interactive OAuth flow must be repeated.
        refresh_expires_at = now + 7 * 24 * 60 * 60
    stored = {
        "access_token": payload.get("access_token") or previous.get("access_token"),
        "refresh_token": refresh,
        "token_type": payload.get("token_type") or previous.get("token_type") or "Bearer",
        "scope": payload.get("scope") or previous.get("scope"),
        "access_expires_at": now + float(payload.get("expires_in") or 1800),
        "refresh_expires_at": refresh_expires_at,
        "updated_at": _utc_now().isoformat(),
    }
    _write_private_json(token_path(), stored)


async def _refresh_access_token() -> str:
    current = _read_json(token_path())
    refresh_token = str(current.get("refresh_token") or "")
    if not refresh_token:
        raise RuntimeError("Schwab refresh token is missing; authorize again")
    if float(current.get("refresh_expires_at") or 0) <= _epoch_now() + 60:
        raise RuntimeError("Schwab refresh token expired; authorize again")
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.post(
            f"{AUTH_BASE}/token",
            headers={
                "Authorization": _basic_auth_header(),
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={"grant_type": "refresh_token", "refresh_token": refresh_token},
        )
        response.raise_for_status()
        payload = response.json()
    _store_tokens(payload, initial=False)
    token = str(_read_json(token_path()).get("access_token") or "")
    if not token:
        raise RuntimeError("Schwab refresh did not return an access token")
    return token


async def access_token() -> str:
    current = _read_json(token_path())
    token = str(current.get("access_token") or "")
    if token and float(current.get("access_expires_at") or 0) > _epoch_now() + 90:
        return token
    return await _refresh_access_token()


async def api_get(path: str, *, market_data: bool = False, params: dict[str, Any] | None = None) -> Any:
    if not configured():
        raise RuntimeError("Schwab integration is not configured")
    token = await access_token()
    base = MARKET_BASE if market_data else TRADER_BASE
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.get(
            f"{base}{path}",
            params=params,
            headers={"Authorization": f"Bearer {token}"},
        )
        if response.status_code == 401:
            token = await _refresh_access_token()
            response = await client.get(
                f"{base}{path}",
                params=params,
                headers={"Authorization": f"Bearer {token}"},
            )
        response.raise_for_status()
        return response.json()


async def account_number_map() -> list[dict[str, Any]]:
    raw = await api_get("/accounts/accountNumbers")
    return raw if isinstance(raw, list) else []


def _masked_account(account_number: str | None) -> str:
    raw = str(account_number or "")
    return f"••••{raw[-4:]}" if raw else "Schwab account"


async def positions() -> dict[str, Any]:
    mappings = await account_number_map()
    accounts: list[dict[str, Any]] = []
    for item in mappings:
        account_hash = str(item.get("hashValue") or "")
        if not account_hash:
            continue
        payload = await api_get(f"/accounts/{account_hash}", params={"fields": "positions"})
        securities = payload.get("securitiesAccount") if isinstance(payload, dict) else None
        securities = securities if isinstance(securities, dict) else {}
        rows = []
        for position in securities.get("positions") or []:
            instrument = position.get("instrument") or {}
            rows.append(
                {
                    "symbol": instrument.get("symbol"),
                    "asset_type": instrument.get("assetType"),
                    "long_quantity": position.get("longQuantity"),
                    "short_quantity": position.get("shortQuantity"),
                    "average_price": position.get("averagePrice"),
                    "market_value": position.get("marketValue"),
                    "current_day_profit_loss": position.get("currentDayProfitLoss"),
                    "current_day_profit_loss_pct": position.get("currentDayProfitLossPercentage"),
                }
            )
        balances = securities.get("currentBalances") or {}
        accounts.append(
            {
                "account": _masked_account(item.get("accountNumber")),
                "type": securities.get("type"),
                "positions": rows,
                "balances": {
                    "liquidation_value": balances.get("liquidationValue"),
                    "cash_balance": balances.get("cashBalance"),
                    "available_funds": balances.get("availableFunds"),
                    "buying_power": balances.get("buyingPower"),
                },
            }
        )
    return {"accounts": accounts, "account_count": len(accounts), "provider": "schwab", "read_only": True}


async def quotes(symbols: list[str]) -> Any:
    cleaned = [symbol.strip().upper() for symbol in symbols if symbol.strip()]
    if not cleaned:
        return {}
    return await api_get("/quotes", market_data=True, params={"symbols": ",".join(cleaned)})


async def option_chain(symbol: str, **filters: Any) -> Any:
    params: dict[str, Any] = {"symbol": symbol.strip().upper()}
    allowed = {
        "contractType", "strikeCount", "includeUnderlyingQuote", "strategy",
        "interval", "strike", "range", "fromDate", "toDate", "volatility",
        "underlyingPrice", "interestRate", "daysToExpiration", "expMonth", "optionType",
    }
    for key, value in filters.items():
        if key in allowed and value not in (None, ""):
            params[key] = value
    return await api_get("/chains", market_data=True, params=params)
