from __future__ import annotations

import asyncio
import copy
import os
import time
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter

# app_schwab imports the base app before this router, so importing app here reuses
# the initialized market-data router without creating another FastAPI instance.
import app as dashboard_app
from manual_focus import list_focus_items
from market_focus import (
    MAG7,
    MARKET_CORE,
    SECTOR_MEMBERS,
    SECTOR_NAMES,
    build_priority_queue,
    rank_movers,
    rank_sectors,
    selected_sector_etfs,
)
from schwab_market_data import latest_quote as schwab_latest_quote
from schwab_market_data import market_data_ready as schwab_market_ready
from schwab_market_data import radar_bars as schwab_radar_bars

router = APIRouter(prefix="/api/market", tags=["market-focus"])

_CACHE: dict[str, Any] = {"expires": 0.0, "data": None}
_LOCK = asyncio.Lock()


def _env_int(name: str, default: int, minimum: int = 0, maximum: int = 100) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


def _env_float(name: str, default: float, minimum: float = 1.0) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(minimum, value)


def _dedupe(symbols: list[str]) -> list[str]:
    output: list[str] = []
    for raw in symbols:
        symbol = str(raw or "").strip().upper()
        if symbol and symbol not in output:
            output.append(symbol)
    return output


async def _snapshots(symbols: list[str]) -> tuple[list[dict[str, Any]], dict[str, str], list[str]]:
    symbols = _dedupe(symbols)
    snapshots: list[dict[str, Any]] = []
    errors: dict[str, str] = {}
    fallback_symbols: list[str] = []
    remaining = list(symbols)

    if dashboard_app._schwab_is_primary() and schwab_market_ready():
        rows_by_symbol, schwab_errors = await schwab_radar_bars(
            symbols,
            limit=120,
            concurrency=dashboard_app.SCHWAB_RADAR_CONCURRENCY,
        )
        for symbol, rows in rows_by_symbol.items():
            snapshot = dashboard_app._technical_snapshot(dashboard_app._rows_to_frame(rows), symbol)
            if snapshot:
                snapshot["provider"] = "schwab"
                snapshots.append(snapshot)
        remaining = [symbol for symbol in symbols if symbol not in rows_by_symbol]
        errors.update({f"schwab:{symbol}": reason for symbol, reason in schwab_errors.items()})

    if remaining:
        try:
            alpaca_rows = await dashboard_app._alpaca_radar_snapshots(remaining)
            snapshots.extend(alpaca_rows)
            fallback_symbols = [str(row.get("symbol") or "").upper() for row in alpaca_rows]
        except Exception as exc:
            errors[dashboard_app._alpaca_provider_name()] = type(exc).__name__

    return snapshots, errors, fallback_symbols


async def _spx_context() -> dict[str, Any]:
    if not schwab_market_ready():
        return {"available": False, "symbol": "SPX", "reason": "Schwab market data is not ready"}
    last_error: str | None = None
    for symbol in ("$SPX", "SPX"):
        try:
            payload = await schwab_latest_quote(symbol)
            quote = payload.get("quote") if isinstance(payload, dict) else None
            if isinstance(quote, dict) and float(quote.get("mid") or 0.0) > 0:
                return {
                    "available": True,
                    "symbol": "SPX",
                    "provider_symbol": symbol,
                    "provider": "schwab",
                    "price": quote.get("mid"),
                    "bid": quote.get("bid"),
                    "ask": quote.get("ask"),
                    "timestamp": quote.get("timestamp"),
                }
        except Exception as exc:
            last_error = type(exc).__name__
    return {"available": False, "symbol": "SPX", "reason": last_error or "No usable SPX quote"}


def _market_tone(snapshot_by_symbol: dict[str, dict[str, Any]]) -> dict[str, Any]:
    rows = [snapshot_by_symbol.get(symbol) for symbol in MARKET_CORE]
    rows = [row for row in rows if isinstance(row, dict)]
    if not rows:
        return {"state": "UNKNOWN", "score": 50.0, "note": "SPY/QQQ context is unavailable."}
    scores = [float(row.get("score") or 50.0) for row in rows]
    score = sum(scores) / len(scores)
    if score >= 58:
        state = "RISK_ON"
        note = "SPY and QQQ are broadly supportive of bullish setups."
    elif score <= 42:
        state = "RISK_OFF"
        note = "SPY and QQQ are broadly supportive of bearish setups."
    else:
        state = "MIXED"
        note = "The broad market is mixed; demand stronger stock/sector confirmation."
    return {"state": state, "score": round(score, 1), "note": note}


async def build_market_focus() -> dict[str, Any]:
    sector_etfs = list(SECTOR_NAMES)
    first_pass_symbols = _dedupe(MARKET_CORE + MAG7 + sector_etfs)
    first_pass, errors, fallback = await _snapshots(first_pass_symbols)
    snapshot_by_symbol = {str(row.get("symbol") or "").upper(): row for row in first_pass if row.get("symbol")}

    spy_momentum = float((snapshot_by_symbol.get("SPY") or {}).get("momentum_30m_pct") or 0.0)
    sector_rows = rank_sectors(
        [snapshot_by_symbol[symbol] for symbol in sector_etfs if symbol in snapshot_by_symbol],
        spy_momentum=spy_momentum,
    )
    selected_etfs = selected_sector_etfs(
        sector_rows,
        leaders=_env_int("MNT_FOCUS_LEADING_SECTORS", 2, 1, 4),
        laggards=_env_int("MNT_FOCUS_LAGGING_SECTORS", 1, 0, 3),
    )

    sector_by_symbol: dict[str, str] = {}
    mover_universe: list[str] = []
    for etf in selected_etfs:
        for symbol in SECTOR_MEMBERS.get(etf, []):
            sector_by_symbol.setdefault(symbol, etf)
            if symbol not in mover_universe:
                mover_universe.append(symbol)

    missing_movers = [symbol for symbol in mover_universe if symbol not in snapshot_by_symbol]
    mover_extra, mover_errors, mover_fallback = await _snapshots(missing_movers)
    errors.update(mover_errors)
    fallback.extend(symbol for symbol in mover_fallback if symbol not in fallback)
    for row in mover_extra:
        symbol = str(row.get("symbol") or "").upper()
        if symbol:
            snapshot_by_symbol[symbol] = row

    sector_strength_by_etf = {str(row.get("symbol") or "").upper(): float(row.get("strength") or 0.0) for row in sector_rows}
    movers = rank_movers(
        [snapshot_by_symbol[symbol] for symbol in mover_universe if symbol in snapshot_by_symbol],
        sector_by_symbol=sector_by_symbol,
        sector_strength_by_etf=sector_strength_by_etf,
    )
    mag7_snapshots = [snapshot_by_symbol[symbol] for symbol in MAG7 if symbol in snapshot_by_symbol]
    priority = build_priority_queue(
        mag7_snapshots=mag7_snapshots,
        movers=movers,
        max_items=_env_int("MNT_MARKET_FOCUS_DYNAMIC_SLOTS", 8, 4, 16),
        mag7_slots=_env_int("MNT_MARKET_FOCUS_MAG7_SLOTS", 2, 1, 7),
        mover_slots=_env_int("MNT_MARKET_FOCUS_MOVER_SLOTS", 4, 1, 10),
    )

    manual_items = list_focus_items()
    manual_symbols = [str(item.get("symbol") or "").upper() for item in manual_items if item.get("symbol")]
    provider_counts: dict[str, int] = {}
    for row in snapshot_by_symbol.values():
        provider = str(row.get("provider") or "unknown")
        provider_counts[provider] = provider_counts.get(provider, 0) + 1

    leading_count = _env_int("MNT_FOCUS_LEADING_SECTORS", 2, 1, 4)
    lagging_count = _env_int("MNT_FOCUS_LAGGING_SECTORS", 1, 0, 3)
    leading = sector_rows[:leading_count]
    lagging = list(reversed(sector_rows))[:lagging_count] if lagging_count else []

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "SECTOR_MOVER_FOCUS",
        "research_only": True,
        "market_tone": _market_tone(snapshot_by_symbol),
        "spx": await _spx_context(),
        "core": [snapshot_by_symbol.get(symbol, {"symbol": symbol, "available": False}) for symbol in MARKET_CORE],
        "mag7": [snapshot_by_symbol.get(symbol, {"symbol": symbol, "available": False}) for symbol in MAG7],
        "leading_sectors": leading,
        "lagging_sectors": lagging,
        "selected_sector_etfs": selected_etfs,
        "movers": movers[:12],
        "priority_queue": priority,
        "priority_symbols": [row["symbol"] for row in priority],
        "manual_focus": manual_items,
        "manual_symbols": manual_symbols,
        "fast_scan_symbols": _dedupe(MARKET_CORE + MAG7 + mover_universe + manual_symbols),
        "provider_counts": provider_counts,
        "fallback_symbols": _dedupe(fallback),
        "provider_errors": errors,
        "note": (
            "SPX is context only. SPY/QQQ remain core deep-review candidates; Mag-7 and sector movers compete for the remaining dynamic Kronos slots. "
            "Manual focus and active PRE-TRIGGERs are layered ahead of this queue by the alert worker."
        ),
    }


@router.get("/focus")
async def market_focus() -> dict[str, Any]:
    ttl = _env_float("MNT_MARKET_FOCUS_CACHE_SECONDS", 45.0, 10.0)
    now = time.monotonic()
    if _CACHE["data"] is not None and now < _CACHE["expires"]:
        cached = copy.deepcopy(_CACHE["data"])
        cached["cached"] = True
        return cached

    async with _LOCK:
        now = time.monotonic()
        if _CACHE["data"] is not None and now < _CACHE["expires"]:
            cached = copy.deepcopy(_CACHE["data"])
            cached["cached"] = True
            return cached
        data = await build_market_focus()
        data["cached"] = False
        _CACHE["data"] = copy.deepcopy(data)
        _CACHE["expires"] = time.monotonic() + ttl
        return data
