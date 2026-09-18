from __future__ import annotations

import os
from typing import Any

import httpx

import mnt_alert_worker as base_worker
from market_focus import MAG7, MARKET_CORE, SECTOR_MEMBERS


def _focus_universe() -> list[str]:
    symbols: list[str] = []
    for symbol in base_worker._symbols() + MARKET_CORE + MAG7:
        symbol = str(symbol or "").upper()
        if symbol and symbol not in symbols:
            symbols.append(symbol)
    for members in SECTOR_MEMBERS.values():
        for symbol in members:
            symbol = str(symbol or "").upper()
            if symbol and symbol not in symbols:
                symbols.append(symbol)
    return symbols


async def _fetch_market_focus(client: httpx.AsyncClient, base_url: str, limit: int = 20) -> dict[str, Any]:
    response = await client.get(f"{base_url}/api/market/focus", timeout=30.0)
    response.raise_for_status()
    body = response.json()
    return body if isinstance(body, dict) else {}


def _shortlist_from_focus(
    focus: dict[str, Any] | None,
    configured_symbols: list[str],
    *,
    limit: int = 4,
) -> list[str]:
    limit = max(1, int(limit))
    output: list[str] = []
    for raw in (focus or {}).get("priority_symbols") or []:
        symbol = str(raw or "").strip().upper()
        if symbol and symbol not in output:
            output.append(symbol)
        if len(output) >= limit:
            return output
    for symbol in configured_symbols:
        symbol = str(symbol or "").strip().upper()
        if symbol and symbol not in output:
            output.append(symbol)
        if len(output) >= limit:
            break
    return output


async def scan_once(client: httpx.AsyncClient, state: base_worker.AlertState) -> list[dict[str, Any]]:
    """Use Market Focus Mode to choose symbols, then reuse the proven alert engine."""
    original_fetch = base_worker.fetch_radar
    original_shortlist = base_worker.shortlist_from_radar
    original_symbols = base_worker._symbols
    previous_fusion_shortlist = os.environ.get("MNT_FUSION_SHORTLIST")
    focus_shortlist = os.getenv("MNT_MARKET_FOCUS_FUSION_SHORTLIST", "12").strip() or "12"
    captured_focus: dict[str, Any] = {}

    async def fetch_focus(client_arg: httpx.AsyncClient, base_url: str, limit: int = 20) -> dict[str, Any]:
        nonlocal captured_focus
        captured_focus = await _fetch_market_focus(client_arg, base_url, limit)
        return captured_focus

    try:
        base_worker.fetch_radar = fetch_focus
        base_worker.shortlist_from_radar = _shortlist_from_focus
        base_worker._symbols = _focus_universe
        os.environ["MNT_FUSION_SHORTLIST"] = focus_shortlist
        results = await base_worker.scan_once(client, state)
    finally:
        base_worker.fetch_radar = original_fetch
        base_worker.shortlist_from_radar = original_shortlist
        base_worker._symbols = original_symbols
        if previous_fusion_shortlist is None:
            os.environ.pop("MNT_FUSION_SHORTLIST", None)
        else:
            os.environ["MNT_FUSION_SHORTLIST"] = previous_fusion_shortlist

    for item in results:
        if item.get("stage") == "radar":
            item["stage"] = "market_focus"
            item["focus_mode"] = True
            item["market_tone"] = (captured_focus.get("market_tone") or {}).get("state")
            item["leading_sectors"] = [row.get("sector") for row in (captured_focus.get("leading_sectors") or [])]
            item["lagging_sectors"] = [row.get("sector") for row in (captured_focus.get("lagging_sectors") or [])]
            item["dynamic_priority"] = captured_focus.get("priority_symbols") or []
            item["market_data_fallbacks"] = captured_focus.get("fallback_symbols") or []
            break
    return results
