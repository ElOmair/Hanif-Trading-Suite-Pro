from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo
from datetime import datetime

import httpx

from alert_policy import build_discord_message, classify_alert
from shadow_trade_store import record_ready_shadow_trade

ET = ZoneInfo("America/New_York")
DEFAULT_SYMBOLS = "SPY,QQQ,NVDA,TSLA,AAPL,AMD,META,AMZN,MSFT,GOOGL,PLTR,COIN"


def _env_float(name: str, default: float, minimum: float = 0.0) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(minimum, value)


def _env_int(name: str, default: int, minimum: int = 0) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(minimum, value)


def _symbols() -> list[str]:
    raw = os.getenv("MNT_ALERT_SYMBOLS", DEFAULT_SYMBOLS)
    values: list[str] = []
    seen: set[str] = set()
    for item in raw.split(","):
        symbol = item.strip().upper()
        if symbol and symbol not in seen:
            values.append(symbol)
            seen.add(symbol)
    return values


def market_scan_active(now: datetime | None = None) -> bool:
    now = now or datetime.now(ET)
    if now.tzinfo is None:
        now = now.replace(tzinfo=ET)
    else:
        now = now.astimezone(ET)
    if now.weekday() >= 5:
        return False
    minute = now.hour * 60 + now.minute
    start = int(_env_float("MNT_ALERT_START_MINUTE_ET", 9 * 60 + 25, 0))
    end = int(_env_float("MNT_ALERT_END_MINUTE_ET", 16 * 60 + 5, 0))
    return start <= minute <= end


def rank_alert_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Rank alertable scan results without changing their underlying MnT score."""
    def key(item: dict[str, Any]) -> tuple[int, float, float]:
        classification = item.get("classification") or {}
        state = str(classification.get("state") or "")
        state_rank = 2 if state == "READY" else 1 if state == "PRE_TRIGGER" else 0
        try:
            score = float(classification.get("score") or 0.0)
        except (TypeError, ValueError):
            score = 0.0
        try:
            coverage = float(classification.get("coverage_pct") or 0.0)
        except (TypeError, ValueError):
            coverage = 0.0
        return state_rank, score, coverage

    return sorted(candidates, key=key, reverse=True)


def shortlist_from_radar(
    radar: dict[str, Any] | None,
    configured_symbols: list[str],
    *,
    limit: int = 4,
) -> list[str]:
    """Choose a small long/short-balanced set for expensive Fusion analysis."""
    configured = {symbol.upper() for symbol in configured_symbols}
    limit = max(1, int(limit))
    if not radar or not configured:
        return configured_symbols[:limit]

    def normalized(rows: Any, direction: str) -> list[dict[str, Any]]:
        output = []
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            symbol = str(row.get("symbol") or "").upper()
            if symbol not in configured:
                continue
            try:
                rank_score = float(row.get("rank_score") or 0.0)
            except (TypeError, ValueError):
                rank_score = 0.0
            output.append({"symbol": symbol, "direction": direction, "rank_score": rank_score})
        output.sort(key=lambda item: item["rank_score"], reverse=True)
        return output

    longs = normalized(radar.get("longs"), "LONG")
    shorts = normalized(radar.get("shorts"), "SHORT")
    per_side = max(1, limit // 2)
    selected = longs[:per_side] + shorts[:per_side]

    selected_symbols = {item["symbol"] for item in selected}
    leftovers = [item for item in longs[per_side:] + shorts[per_side:] if item["symbol"] not in selected_symbols]
    leftovers.sort(key=lambda item: item["rank_score"], reverse=True)
    selected.extend(leftovers[: max(0, limit - len(selected))])

    result: list[str] = []
    for item in selected:
        if item["symbol"] not in result:
            result.append(item["symbol"])
        if len(result) >= limit:
            break
    return result or configured_symbols[:limit]


class AlertState:
    def __init__(self, path: Path):
        self.path = path
        self.data: dict[str, dict[str, Any]] = {}
        self.load()

    def load(self) -> None:
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                self.data = raw
        except Exception:
            self.data = {}

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(self.path.suffix + ".tmp")
        temp.write_text(json.dumps(self.data, indent=2, sort_keys=True), encoding="utf-8")
        temp.replace(self.path)

    def should_send(self, symbol: str, classification: dict[str, Any], cooldown_seconds: float) -> bool:
        state = str(classification.get("state") or "")
        score = classification.get("score")
        now = time.time()
        previous = self.data.get(symbol) or {}
        previous_state = str(previous.get("state") or "")
        previous_score = previous.get("score")
        previous_time = float(previous.get("sent_at") or 0.0)

        if state == "READY" and previous_state != "READY":
            return True
        if state == "PRE_TRIGGER" and previous_state not in {"PRE_TRIGGER", "READY"}:
            return True
        if state == previous_state and now - previous_time < cooldown_seconds:
            return False
        try:
            if previous_score is not None and score is not None and abs(float(score) - float(previous_score)) < 5.0:
                return False
        except (TypeError, ValueError):
            pass
        return state in {"PRE_TRIGGER", "READY"}

    def mark_sent(self, symbol: str, classification: dict[str, Any]) -> None:
        self.data[symbol] = {
            "state": classification.get("state"),
            "score": classification.get("score"),
            "coverage_pct": classification.get("coverage_pct"),
            "sent_at": time.time(),
        }
        self.save()

    def observe(self, symbol: str, classification: dict[str, Any]) -> None:
        if classification.get("state") in {"WATCH", "NO_DIRECTION", "REJECTED", "NO_CHASE"}:
            previous = self.data.get(symbol)
            if previous and previous.get("state") != "READY":
                self.data.pop(symbol, None)
                self.save()


async def fetch_radar(client: httpx.AsyncClient, base_url: str, limit: int = 20) -> dict[str, Any]:
    response = await client.get(f"{base_url}/api/radar", params={"limit": max(3, min(20, limit))})
    response.raise_for_status()
    body = response.json()
    return body if isinstance(body, dict) else {}


async def fetch_fusion(client: httpx.AsyncClient, base_url: str, symbol: str, max_contract_cost: float | None) -> dict[str, Any]:
    params = {}
    if max_contract_cost is not None:
        params["max_contract_cost"] = max_contract_cost
    response = await client.post(f"{base_url}/api/kronos/fusion/{symbol}", params=params, timeout=90.0)
    response.raise_for_status()
    body = response.json()
    return body if isinstance(body, dict) else {}


async def send_discord(client: httpx.AsyncClient, webhook: str, message: dict[str, Any]) -> None:
    response = await client.post(webhook, json=message)
    response.raise_for_status()


async def scan_once(client: httpx.AsyncClient, state: AlertState) -> list[dict[str, Any]]:
    base_url = os.getenv("MNT_DASHBOARD_API_URL", "http://127.0.0.1:8080").rstrip("/")
    webhook = os.getenv("MNT_DISCORD_WEBHOOK_URL", "").strip()
    pretrigger_score = _env_float("MNT_PRETRIGGER_SCORE", 72.0, 0.0)
    pretrigger_coverage = _env_float("MNT_PRETRIGGER_COVERAGE", 55.0, 0.0)
    cooldown = _env_float("MNT_ALERT_COOLDOWN_SECONDS", 900.0, 0.0)
    max_pretrigger_per_scan = _env_int("MNT_MAX_PRETRIGGER_ALERTS_PER_SCAN", 3, 0)
    max_ready_per_scan = _env_int("MNT_MAX_READY_ALERTS_PER_SCAN", 5, 0)
    fusion_shortlist = _env_int("MNT_FUSION_SHORTLIST", 4, 1)
    max_contract_cost_raw = os.getenv("MNT_MAX_CONTRACT_COST", "300").strip()
    max_contract_cost = float(max_contract_cost_raw) if max_contract_cost_raw else None
    configured_symbols = _symbols()

    results: list[dict[str, Any]] = []
    alertable: list[dict[str, Any]] = []

    try:
        radar = await fetch_radar(client, base_url, limit=20)
        scan_symbols = shortlist_from_radar(radar, configured_symbols, limit=fusion_shortlist)
        radar_status = {
            "used": True,
            "cached": bool(radar.get("cached")),
            "stale": bool(radar.get("stale")),
            "shortlist": scan_symbols,
        }
    except Exception as exc:
        scan_symbols = configured_symbols[:fusion_shortlist]
        radar_status = {"used": False, "error": type(exc).__name__, "shortlist": scan_symbols}

    results.append({"stage": "radar", **radar_status})

    for symbol in scan_symbols:
        try:
            payload = await fetch_fusion(client, base_url, symbol, max_contract_cost)
            classification = classify_alert(
                payload,
                pretrigger_score=pretrigger_score,
                pretrigger_coverage=pretrigger_coverage,
            )
            item = {
                "symbol": symbol,
                "classification": classification,
                "payload": payload,
                "sent": False,
                "shadow_trade_id": None,
                "suppressed_by_rank": False,
            }
            results.append(item)
            if classification.get("alert") and state.should_send(symbol, classification, cooldown):
                alertable.append(item)
            else:
                state.observe(symbol, classification)
        except Exception as exc:
            results.append({"symbol": symbol, "error": type(exc).__name__, "sent": False})

    ranked = rank_alert_candidates(alertable)
    ready_sent = 0
    pretrigger_sent = 0
    for item in ranked:
        classification = item["classification"]
        alert_state = str(classification.get("state") or "")
        if alert_state == "READY":
            allowed = ready_sent < max_ready_per_scan if max_ready_per_scan > 0 else False
        elif alert_state == "PRE_TRIGGER":
            allowed = pretrigger_sent < max_pretrigger_per_scan if max_pretrigger_per_scan > 0 else False
        else:
            allowed = False

        if not allowed:
            item["suppressed_by_rank"] = True
            continue

        # Record READY candidates that survived ranking even if Discord is down.
        # This creates an unbiased shadow journal of what the alert policy would
        # have surfaced, independent of webhook reliability.
        if alert_state == "READY":
            try:
                item["shadow_trade_id"] = record_ready_shadow_trade(item["payload"], discord_sent=False)
            except Exception as exc:
                item["shadow_record_error"] = type(exc).__name__

        if not webhook:
            continue

        try:
            await send_discord(client, webhook, build_discord_message(item["payload"], classification))
            state.mark_sent(item["symbol"], classification)
            item["sent"] = True
            if alert_state == "READY":
                ready_sent += 1
                try:
                    item["shadow_trade_id"] = record_ready_shadow_trade(item["payload"], discord_sent=True)
                except Exception as exc:
                    item["shadow_delivery_update_error"] = type(exc).__name__
            elif alert_state == "PRE_TRIGGER":
                pretrigger_sent += 1
        except Exception as exc:
            item["send_error"] = type(exc).__name__

    for item in results:
        item.pop("payload", None)
    return results


async def run_forever() -> None:
    interval = _env_float("MNT_ALERT_SCAN_SECONDS", 60.0, 30.0)
    state_path = Path(os.getenv("MNT_ALERT_STATE_FILE", str(Path(__file__).resolve().parent / "data" / "mnt_alert_state.json")))
    state = AlertState(state_path)
    async with httpx.AsyncClient(timeout=20.0) as client:
        while True:
            if market_scan_active():
                results = await scan_once(client, state)
                print(json.dumps({"time": datetime.now(ET).isoformat(), "results": results}, separators=(",", ":")), flush=True)
            await asyncio.sleep(interval)


if __name__ == "__main__":
    asyncio.run(run_forever())
