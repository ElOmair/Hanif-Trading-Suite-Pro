from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from schwab_provider import configured, price_history, quotes, token_status


_TIMEFRAME_REQUESTS: dict[str, tuple[str, int, str, int]] = {
    "1m": ("day", 10, "minute", 1),
    "5m": ("day", 10, "minute", 5),
    "15m": ("day", 10, "minute", 15),
    "30m": ("day", 10, "minute", 30),
    # Schwab's price-history minute frequencies top out below a native one-hour
    # candle on some app entitlements. Request 30m and combine two bars locally.
    "1h": ("day", 10, "minute", 30),
    "1d": ("year", 2, "daily", 1),
}


def _number(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed == parsed else None


def _pick(mapping: dict[str, Any] | None, *keys: str) -> Any:
    if not isinstance(mapping, dict):
        return None
    for key in keys:
        value = mapping.get(key)
        if value not in (None, ""):
            return value
    return None


def market_data_ready() -> bool:
    if not configured():
        return False
    status = token_status()
    return bool(status.get("authorized") and not status.get("reauthorization_required"))


def market_data_status() -> dict[str, Any]:
    status = token_status()
    return {
        "configured": bool(status.get("configured")),
        "authorized": bool(status.get("authorized")),
        "access_token_valid": bool(status.get("access_token_valid")),
        "refresh_token_valid": bool(status.get("refresh_token_valid")),
        "reauthorization_required": bool(status.get("reauthorization_required")),
        "ready": market_data_ready(),
    }


def _symbol_quote(payload: Any, symbol: str) -> dict[str, Any]:
    target = symbol.strip().upper()
    if isinstance(payload, dict):
        direct = payload.get(target) or payload.get(symbol) or payload.get(symbol.lower())
        if isinstance(direct, dict):
            return direct
        if str(payload.get("symbol") or "").upper() == target:
            return payload
    if isinstance(payload, list):
        for row in payload:
            if isinstance(row, dict) and str(row.get("symbol") or "").upper() == target:
                return row
    return {}


def _timestamp_text(quote: dict[str, Any]) -> str | None:
    raw = _pick(quote, "quoteTime", "quoteTimeInLong", "lastTradeTime", "tradeTimeInLong")
    if raw is None:
        return None
    try:
        epoch = float(raw)
    except (TypeError, ValueError):
        return str(raw)
    if epoch > 10_000_000_000:
        epoch /= 1000.0
    try:
        return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat()
    except (OSError, OverflowError, ValueError):
        return None


async def latest_quote(symbol: str) -> dict[str, Any]:
    target = symbol.strip().upper()
    raw = await quotes([target])
    root = _symbol_quote(raw, target)
    quote = root.get("quote") if isinstance(root.get("quote"), dict) else root.get("regular") if isinstance(root.get("regular"), dict) else root
    bid = _number(_pick(quote, "bidPrice", "bid", "bid_price")) or 0.0
    ask = _number(_pick(quote, "askPrice", "ask", "ask_price")) or 0.0
    mark = _number(_pick(quote, "mark", "markPrice")) or 0.0
    last = _number(_pick(quote, "lastPrice", "last", "closePrice")) or 0.0
    midpoint = (bid + ask) / 2.0 if bid > 0 and ask > 0 else 0.0
    mid = mark if mark > 0 else midpoint if midpoint > 0 else last if last > 0 else ask or bid
    return {
        "symbol": target,
        "provider": "schwab",
        "quote": {
            "bid": bid,
            "ask": ask,
            "mid": round(mid, 4) if mid else 0.0,
            "last": last or None,
            "bid_size": _number(_pick(quote, "bidSize", "bid_size")) or 0.0,
            "ask_size": _number(_pick(quote, "askSize", "ask_size")) or 0.0,
            "timestamp": _timestamp_text(quote),
        },
    }


def _candle_rows(payload: Any) -> list[dict[str, Any]]:
    candles = payload.get("candles") if isinstance(payload, dict) else None
    rows: list[dict[str, Any]] = []
    for candle in candles if isinstance(candles, list) else []:
        if not isinstance(candle, dict):
            continue
        timestamp = _number(candle.get("datetime"))
        if timestamp is None:
            continue
        if timestamp > 10_000_000_000:
            timestamp /= 1000.0
        open_price = _number(candle.get("open"))
        high = _number(candle.get("high"))
        low = _number(candle.get("low"))
        close = _number(candle.get("close"))
        volume = _number(candle.get("volume"))
        if None in {open_price, high, low, close, volume}:
            continue
        rows.append(
            {
                "time": int(timestamp),
                "open": float(open_price),
                "high": float(high),
                "low": float(low),
                "close": float(close),
                "volume": float(volume),
            }
        )
    rows.sort(key=lambda row: row["time"])
    return rows


def _aggregate_hourly(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    buckets: dict[int, list[dict[str, Any]]] = {}
    for row in rows:
        bucket = int(row["time"] // 3600 * 3600)
        buckets.setdefault(bucket, []).append(row)
    output: list[dict[str, Any]] = []
    for bucket in sorted(buckets):
        group = sorted(buckets[bucket], key=lambda row: row["time"])
        output.append(
            {
                "time": bucket,
                "open": group[0]["open"],
                "high": max(row["high"] for row in group),
                "low": min(row["low"] for row in group),
                "close": group[-1]["close"],
                "volume": sum(row["volume"] for row in group),
            }
        )
    return output


async def bars(symbol: str, timeframe: str, limit: int = 400) -> dict[str, Any]:
    target = symbol.strip().upper()
    key = timeframe.strip().lower()
    if key not in _TIMEFRAME_REQUESTS:
        raise ValueError(f"Unsupported Schwab timeframe: {timeframe}")
    period_type, period, frequency_type, frequency = _TIMEFRAME_REQUESTS[key]
    raw = await price_history(
        target,
        periodType=period_type,
        period=period,
        frequencyType=frequency_type,
        frequency=frequency,
        needExtendedHoursData=True,
        needPreviousClose=True,
    )
    rows = _candle_rows(raw)
    if key == "1h":
        rows = _aggregate_hourly(rows)
    return {
        "symbol": target,
        "timeframe": key,
        "bars": rows[-max(1, int(limit)):],
        "provider": "schwab",
        "source": "schwab_price_history",
    }


async def radar_bars(
    symbols: list[str],
    *,
    limit: int = 120,
    concurrency: int = 5,
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, str]]:
    semaphore = asyncio.Semaphore(max(1, int(concurrency)))
    results: dict[str, list[dict[str, Any]]] = {}
    errors: dict[str, str] = {}

    async def fetch_one(symbol: str) -> None:
        async with semaphore:
            try:
                payload = await bars(symbol, "5m", limit)
                rows = payload.get("bars") if isinstance(payload, dict) else []
                if isinstance(rows, list) and len(rows) >= 25:
                    results[symbol] = rows
                else:
                    errors[symbol] = "insufficient_bars"
            except Exception as exc:
                errors[symbol] = type(exc).__name__

    await asyncio.gather(*(fetch_one(symbol.strip().upper()) for symbol in symbols if symbol.strip()))
    return results, errors
