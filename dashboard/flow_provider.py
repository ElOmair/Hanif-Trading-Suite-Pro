from __future__ import annotations

import os
import time
from typing import Any

import httpx

BASE_URL = "https://api.unusualwhales.com"
_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}


def _number(value: Any) -> float | None:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if value == value else None


def _clamp(value: float, low: float = -1.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _sentiment_from_ratio(ratio: float) -> str:
    if ratio >= 0.12:
        return "BULLISH"
    if ratio <= -0.12:
        return "BEARISH"
    return "NEUTRAL"


def summarize_flow_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {"available": False, "status": "empty_flow", "source": "unusual_whales"}

    bullish = 0.0
    bearish = 0.0
    dir_delta = 0.0
    transactions = 0.0
    volume = 0.0
    observed = False

    for row in rows:
        row_bullish = _number(row.get("bullish_premium"))
        row_bearish = _number(row.get("bearish_premium"))
        if row_bullish is not None or row_bearish is not None:
            bullish += row_bullish or 0.0
            bearish += row_bearish or 0.0
            observed = True

        net_call = _number(row.get("net_call_prem") or row.get("net_call_premium"))
        net_put = _number(row.get("net_put_prem") or row.get("net_put_premium"))
        if net_call is not None or net_put is not None:
            # Ask-side calls are bullish; ask-side puts are bearish. Net put premium
            # therefore subtracts from directional premium.
            directional = (net_call or 0.0) - (net_put or 0.0)
            if directional >= 0:
                bullish += directional
            else:
                bearish += abs(directional)
            observed = True

        delta = _number(row.get("dir_delta_flow") or row.get("cum_dir_delta"))
        if delta is not None:
            dir_delta += delta
            observed = True
        transactions += _number(row.get("transactions")) or 0.0
        volume += _number(row.get("volume") or row.get("call_volume")) or 0.0
        if row.get("put_volume") is not None:
            volume += _number(row.get("put_volume")) or 0.0

    if not observed:
        return {"available": False, "status": "unsupported_flow_shape", "source": "unusual_whales"}

    premium_total = bullish + bearish
    premium_ratio = (bullish - bearish) / premium_total if premium_total > 0 else 0.0
    delta_ratio = 0.0
    if dir_delta:
        scale = max(abs(dir_delta), volume * 25.0, 1.0)
        delta_ratio = _clamp(dir_delta / scale)

    if premium_total > 0 and dir_delta:
        directional_ratio = _clamp(premium_ratio * 0.7 + delta_ratio * 0.3)
    elif premium_total > 0:
        directional_ratio = _clamp(premium_ratio)
    else:
        directional_ratio = _clamp(delta_ratio)

    sentiment = _sentiment_from_ratio(directional_ratio)
    score = 50.0 + abs(directional_ratio) * 45.0
    return {
        "available": True,
        "status": "ok",
        "source": "unusual_whales",
        "sentiment": sentiment,
        "score": round(min(95.0, max(50.0, score)), 1),
        "directional_ratio": round(directional_ratio, 4),
        "bullish_premium": round(bullish, 2),
        "bearish_premium": round(bearish, 2),
        "directional_delta_flow": round(dir_delta, 2),
        "transactions": int(transactions),
        "option_volume": int(volume),
        "beginner_explanation": (
            "Options traders are leaning bullish: more aggressive option activity is supporting an upward move."
            if sentiment == "BULLISH"
            else "Options traders are leaning bearish: more aggressive option activity is supporting a downward move."
            if sentiment == "BEARISH"
            else "Options activity is mixed, so MnT is not getting a strong directional clue from flow yet."
        ),
        "warning": "Flow shows where aggressive option activity is occurring; it does not prove whether a position is opening, closing, hedging, or part of a spread.",
    }


def _unavailable(status: str, reason: str) -> dict[str, Any]:
    return {"available": False, "status": status, "provider": "unusual_whales", "reason": reason}


async def fetch_flow_context(symbol: str) -> dict[str, Any]:
    provider = os.getenv("MNT_FLOW_PROVIDER", "auto").strip().lower()
    token = os.getenv("UNUSUAL_WHALES_API_TOKEN", "").strip()
    if provider in {"off", "none", "disabled"}:
        return _unavailable("disabled", "The options-flow layer is disabled on this MnT server.")
    if provider not in {"auto", "unusual_whales"}:
        return _unavailable("unsupported_provider", "MnT does not recognize the configured options-flow provider.")
    if not token:
        return _unavailable("not_configured", "A deployable options-flow token is not configured on the MnT server.")

    symbol = symbol.strip().upper()
    cache_seconds = max(10.0, float(os.getenv("MNT_FLOW_CACHE_SECONDS", "30")))
    cached = _CACHE.get(symbol)
    if cached and time.monotonic() < cached[0]:
        payload = dict(cached[1])
        payload["cached"] = True
        return payload

    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    # The first endpoint provides intraday net-premium ticks. The second is kept as
    # a compatibility fallback for accounts/API versions exposing recent flow rows.
    endpoints = (
        f"{BASE_URL}/api/stock/{symbol}/net-prem-ticks",
        f"{BASE_URL}/api/stock/{symbol}/flow-recent",
    )
    last_error = "No options-flow endpoint returned data."
    async with httpx.AsyncClient(timeout=5.0) as client:
        for url in endpoints:
            try:
                response = await client.get(url, headers=headers)
                if response.status_code in {404, 405}:
                    last_error = f"Endpoint unavailable ({response.status_code})."
                    continue
                response.raise_for_status()
                body = response.json()
                rows = body.get("data", body if isinstance(body, list) else [])
                if isinstance(rows, dict):
                    rows = [rows]
                if not isinstance(rows, list):
                    rows = []
                payload = summarize_flow_rows(rows)
                if payload.get("available"):
                    payload["provider"] = "unusual_whales"
                    payload["cached"] = False
                    _CACHE[symbol] = (time.monotonic() + cache_seconds, payload)
                    return payload
                last_error = str(payload.get("status") or "No usable flow rows")
            except Exception as exc:
                last_error = f"{type(exc).__name__}"

    return _unavailable("provider_error", f"Options-flow request failed: {last_error}")
