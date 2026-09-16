from __future__ import annotations

import os
import time
from typing import Any

import httpx

BASE_URL = "https://api.unusualwhales.com"
_CACHE: dict[tuple[str, str], tuple[float, dict[str, Any]]] = {}


def _number(value: Any) -> float | None:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if value == value else None


def _net_gex(row: dict[str, Any]) -> float | None:
    direct = _number(row.get("net_gex") or row.get("net_gamma") or row.get("gex"))
    if direct is not None:
        return direct
    call = _number(row.get("call_gex") or row.get("call_gamma_oi") or row.get("call_gamma"))
    put = _number(row.get("put_gex") or row.get("put_gamma_oi") or row.get("put_gamma"))
    if call is None and put is None:
        return None
    return (call or 0.0) + (put or 0.0)


def derive_oi_gex_levels(rows: list[dict[str, Any]], spot: float | None) -> dict[str, Any]:
    points: list[tuple[float, float]] = []
    for row in rows:
        strike = _number(row.get("strike"))
        net = _net_gex(row)
        if strike is not None and net is not None:
            points.append((strike, net))
    points.sort(key=lambda item: item[0])
    if not points:
        return {"available": False, "status": "empty_profile", "source": "unusual_whales_oi"}

    if spot is None:
        spot = next(
            (_number(row.get("price") or row.get("spot")) for row in rows if _number(row.get("price") or row.get("spot")) is not None),
            None,
        )

    call_wall = None
    put_wall = None
    gamma_flip = None
    gamma_magnet = max(points, key=lambda item: abs(item[1]))[0]

    if spot is not None:
        above = [item for item in points if item[0] >= spot and item[1] > 0]
        below = [item for item in points if item[0] <= spot and item[1] > 0]
        if above:
            call_wall = max(above, key=lambda item: item[1])[0]
        if below:
            put_wall = max(below, key=lambda item: item[1])[0]

        crossings: list[float] = []
        for (s1, g1), (s2, g2) in zip(points, points[1:]):
            if g1 == 0:
                crossings.append(s1)
                continue
            if g2 == 0:
                crossings.append(s2)
                continue
            if (g1 < 0 < g2) or (g1 > 0 > g2):
                ratio = abs(g1) / (abs(g1) + abs(g2))
                crossings.append(s1 + (s2 - s1) * ratio)
        if crossings:
            gamma_flip = min(crossings, key=lambda value: abs(value - spot))

    nearest_net = None
    if spot is not None:
        nearest_net = min(points, key=lambda item: abs(item[0] - spot))[1]
    total_net = sum(net for _, net in points)
    regime_net = nearest_net if nearest_net is not None else total_net
    regime = "POSITIVE_GAMMA_PIN" if regime_net >= 0 else "NEGATIVE_GAMMA_EXPANSION"

    return {
        "available": True,
        "status": "ok",
        "source": "unusual_whales_oi",
        "basis": "open_interest",
        "method": "derived_from_greek_exposure_by_strike",
        "spot": round(spot, 4) if spot is not None else None,
        "call_wall": round(call_wall, 4) if call_wall is not None else None,
        "put_wall": round(put_wall, 4) if put_wall is not None else None,
        "gamma_flip": round(gamma_flip, 4) if gamma_flip is not None else None,
        "gamma_magnet": round(gamma_magnet, 4),
        "net_gex_near_spot": round(nearest_net, 4) if nearest_net is not None else None,
        "net_gex_total": round(total_net, 4),
        "regime": regime,
        "profile_points": len(points),
        "beginner_explanation": (
            "Dealer-positioning math currently favors more back-and-forth or pinning near important option strikes."
            if regime.startswith("POSITIVE")
            else "Dealer-positioning math currently allows moves to accelerate more easily, so breakouts can travel faster."
        ),
        "warning": "This is an open-interest GEX profile. It is useful for structure but does not replace intraday directionalized-volume gamma flow.",
    }


def _not_configured(provider: str) -> dict[str, Any]:
    return {
        "available": False,
        "status": "not_configured",
        "provider": provider,
        "reason": "A deployable gamma data token is not configured on the MnT server.",
    }


async def fetch_gamma_context(symbol: str, spot: float | None = None) -> dict[str, Any]:
    provider = os.getenv("MNT_GAMMA_PROVIDER", "auto").strip().lower()
    token = os.getenv("UNUSUAL_WHALES_API_TOKEN", "").strip()
    if provider in {"off", "none", "disabled"}:
        return _not_configured(provider)
    if provider not in {"auto", "unusual_whales", "unusual_whales_oi"}:
        return {
            "available": False,
            "status": "unsupported_provider",
            "provider": provider,
            "reason": "MnT does not recognize the configured gamma provider.",
        }
    if not token:
        return _not_configured("unusual_whales_oi")

    symbol = symbol.strip().upper()
    cache_seconds = max(15.0, float(os.getenv("MNT_GAMMA_CACHE_SECONDS", "60")))
    cache_key = (symbol, "oi")
    cached = _CACHE.get(cache_key)
    if cached and time.monotonic() < cached[0]:
        payload = dict(cached[1])
        payload["cached"] = True
        if spot is not None and payload.get("spot") is None:
            payload["spot"] = spot
        return payload

    url = f"{BASE_URL}/api/stock/{symbol}/greek-exposure/strike"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(url, headers=headers)
        response.raise_for_status()
        body = response.json()
        rows = body.get("data", body if isinstance(body, list) else [])
        if not isinstance(rows, list):
            rows = []
        payload = derive_oi_gex_levels(rows, spot)
        payload["provider"] = "unusual_whales"
        payload["cached"] = False
        _CACHE[cache_key] = (time.monotonic() + cache_seconds, payload)
        return payload
    except Exception as exc:
        return {
            "available": False,
            "status": "provider_error",
            "provider": "unusual_whales",
            "reason": f"Gamma data request failed: {type(exc).__name__}",
        }
