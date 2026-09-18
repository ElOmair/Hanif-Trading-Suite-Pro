from __future__ import annotations

import os
from collections import defaultdict
from typing import Any, Iterable

import httpx

from option_shadow_store import due_option_marks, record_option_mark

ALPACA_OPTION_QUOTES_URL = "https://data.alpaca.markets/v1beta1/options/quotes/latest"
MAX_SYMBOLS_PER_REQUEST = 100


def _credentials() -> tuple[str, str]:
    return (
        os.getenv("ALPACA_API_KEY", "").strip(),
        os.getenv("ALPACA_SECRET_KEY", "").strip(),
    )


def _chunks(values: list[str], size: int = MAX_SYMBOLS_PER_REQUEST) -> Iterable[list[str]]:
    size = max(1, min(MAX_SYMBOLS_PER_REQUEST, int(size)))
    for index in range(0, len(values), size):
        yield values[index : index + size]


def _normalize_quote(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    bid = value.get("bp", value.get("bid"))
    ask = value.get("ap", value.get("ask"))
    timestamp = value.get("t", value.get("timestamp"))
    return {"bid": bid, "ask": ask, "timestamp": timestamp}


def parse_latest_quotes(payload: Any) -> dict[str, dict[str, Any]]:
    """Normalize Alpaca's latest multi-option-quote response.

    Alpaca currently returns a top-level `quotes` mapping keyed by OCC contract
    symbol. The parser also accepts a direct symbol mapping so fixtures and future
    response wrappers do not force the worker to change.
    """
    if not isinstance(payload, dict):
        return {}
    raw = payload.get("quotes") if isinstance(payload.get("quotes"), dict) else payload
    output: dict[str, dict[str, Any]] = {}
    for symbol, value in raw.items():
        normalized = _normalize_quote(value)
        if normalized is not None:
            output[str(symbol).upper()] = normalized
    return output


async def _request_quotes(
    client: httpx.AsyncClient,
    symbols: list[str],
    *,
    api_key: str,
    secret_key: str,
    feed: str | None,
) -> tuple[dict[str, dict[str, Any]], str | None]:
    params: dict[str, Any] = {"symbols": ",".join(symbols)}
    if feed:
        params["feed"] = feed
    response = await client.get(
        ALPACA_OPTION_QUOTES_URL,
        params=params,
        headers={
            "APCA-API-KEY-ID": api_key,
            "APCA-API-SECRET-KEY": secret_key,
        },
        timeout=15.0,
    )
    response.raise_for_status()
    return parse_latest_quotes(response.json()), feed


async def fetch_latest_option_quotes(
    client: httpx.AsyncClient,
    symbols: Iterable[str],
    *,
    api_key: str | None = None,
    secret_key: str | None = None,
    feed: str | None = None,
) -> tuple[dict[str, dict[str, Any]], str | None]:
    """Fetch latest bid/ask quotes for up to 100 symbols per Alpaca request.

    If an explicitly requested/default OPRA feed is forbidden for the account,
    MnT retries that batch once with Alpaca's `indicative` options feed. This is
    calibration data, so the actual feed used is stored with every mark.
    """
    env_key, env_secret = _credentials()
    api_key = (api_key or env_key).strip()
    secret_key = (secret_key or env_secret).strip()
    if not api_key or not secret_key:
        raise RuntimeError("Alpaca credentials are missing")

    configured = (feed if feed is not None else os.getenv("MNT_ALPACA_OPTION_FEED", "")).strip().lower()
    configured_feed = configured if configured in {"opra", "indicative"} else None
    unique = sorted({str(symbol).strip().upper() for symbol in symbols if str(symbol).strip()})
    quotes: dict[str, dict[str, Any]] = {}
    feeds_used: set[str] = set()

    for batch in _chunks(unique):
        try:
            batch_quotes, used = await _request_quotes(
                client,
                batch,
                api_key=api_key,
                secret_key=secret_key,
                feed=configured_feed,
            )
            quotes.update(batch_quotes)
            if used:
                feeds_used.add(used)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code != 403 or configured_feed == "indicative":
                raise
            batch_quotes, _ = await _request_quotes(
                client,
                batch,
                api_key=api_key,
                secret_key=secret_key,
                feed="indicative",
            )
            quotes.update(batch_quotes)
            feeds_used.add("indicative")

    if not feeds_used:
        effective_feed = configured_feed or "account-default"
    elif len(feeds_used) == 1:
        effective_feed = next(iter(feeds_used))
    else:
        effective_feed = "+".join(sorted(feeds_used))
    return quotes, effective_feed


async def refresh_due_option_marks(client: httpx.AsyncClient) -> dict[str, Any]:
    """Mark due READY option contracts without placing any brokerage order."""
    due = due_option_marks()
    if not due:
        return {"due": 0, "quoted_contracts": 0, "marks_recorded": 0, "status": "nothing_due"}

    key, secret = _credentials()
    if not key or not secret:
        return {
            "due": len(due),
            "quoted_contracts": 0,
            "marks_recorded": 0,
            "status": "credentials_missing",
        }

    by_symbol: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in due:
        by_symbol[str(item["option_symbol"]).upper()].append(item)

    try:
        quotes, feed = await fetch_latest_option_quotes(client, by_symbol.keys(), api_key=key, secret_key=secret)
    except Exception as exc:
        return {
            "due": len(due),
            "quoted_contracts": 0,
            "marks_recorded": 0,
            "status": "quote_error",
            "error": type(exc).__name__,
        }

    recorded = 0
    missing_quotes = 0
    for symbol, items in by_symbol.items():
        quote = quotes.get(symbol)
        if not quote:
            missing_quotes += len(items)
            continue
        for item in items:
            if record_option_mark(item, quote, feed=feed) is not None:
                recorded += 1

    return {
        "due": len(due),
        "quoted_contracts": len(quotes),
        "marks_recorded": recorded,
        "missing_quotes": missing_quotes,
        "feed": feed,
        "status": "ok",
    }
