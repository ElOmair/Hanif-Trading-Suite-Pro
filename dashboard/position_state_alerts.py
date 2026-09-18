from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

import httpx

from manual_focus import list_focus_items

ROOT = Path(__file__).resolve().parent
URGENT_STATES = {"RISK_OFF", "TIME_RISK", "EXIT_REVIEW"}


def _enabled() -> bool:
    raw = os.getenv("MNT_POSITION_ALERTS_ENABLED", "true").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _state_path() -> Path:
    return Path(os.getenv("MNT_POSITION_ALERT_STATE_FILE", str(ROOT / "data" / "mnt_position_alert_state.json")))


def _cooldown_seconds() -> float:
    try:
        return max(0.0, float(os.getenv("MNT_POSITION_ALERT_COOLDOWN_SECONDS", "300")))
    except (TypeError, ValueError):
        return 300.0


class PositionAlertState:
    def __init__(self, path: Path | None = None):
        self.path = path or _state_path()
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

    def observe(self, symbol: str, kind: str, state: str) -> dict[str, Any]:
        key = f"{symbol.upper()}:{kind.upper()}"
        now = time.time()
        previous = self.data.get(key) or {}
        previous_state = str(previous.get("state") or "").upper() or None
        last_alert = float(previous.get("last_alert_at") or 0.0)
        changed = previous_state is not None and previous_state != state
        urgent = state in URGENT_STATES
        notify = bool(changed and (urgent or now - last_alert >= _cooldown_seconds()))
        self.data[key] = {
            "state": state,
            "observed_at": now,
            "last_alert_at": now if notify else last_alert,
        }
        self.save()
        return {
            "previous_state": previous_state,
            "state": state,
            "changed": changed,
            "notify": notify,
            "baseline": previous_state is None,
        }


def _pnl_text(analysis: dict[str, Any], kind: str) -> str:
    pnl = analysis.get("pnl") if isinstance(analysis.get("pnl"), dict) else {}
    pct_value = pnl.get("exit_pct") if kind == "OPEN_OPTION" else pnl.get("pct")
    dollars = pnl.get("exit_dollars") if kind == "OPEN_OPTION" else pnl.get("dollars")
    try:
        pct_text = f"{float(pct_value):+.1f}%" if pct_value is not None else "—"
    except (TypeError, ValueError):
        pct_text = "—"
    try:
        dollar_text = f"${float(dollars):+,.2f}" if dollars is not None else "—"
    except (TypeError, ValueError):
        dollar_text = "—"
    return f"{pct_text} · {dollar_text}"


def build_position_alert_message(
    *,
    item: dict[str, Any],
    analysis: dict[str, Any],
    previous_state: str | None,
) -> dict[str, Any]:
    symbol = str(item.get("symbol") or "").upper()
    kind = str(item.get("kind") or "").upper()
    management = analysis.get("management") if isinstance(analysis.get("management"), dict) else {}
    state = str(management.get("state") or "WATCH").upper()
    headline = str(management.get("headline") or "MnT position state changed.")
    next_step = str(management.get("next_step") or "Review the managed position.")
    current = analysis.get("current") if isinstance(analysis.get("current"), dict) else {}
    if kind == "OPEN_OPTION":
        current_text = f"Bid ${current.get('bid') or '—'} · Mark ${current.get('mark') or '—'}"
        position_label = "OPEN OPTION"
    else:
        current_text = f"Price ${current.get('price') or '—'} · Exit ref ${current.get('exit_reference') or '—'}"
        position_label = "OPEN STOCK"

    transition = f"{previous_state or 'BASELINE'} → {state}"
    return {
        "content": f"📌 MnT Position Alert — {symbol}",
        "embeds": [
            {
                "title": f"{symbol} · {position_label} · {state.replace('_', ' ')}",
                "description": headline,
                "fields": [
                    {"name": "State change", "value": transition, "inline": True},
                    {"name": "P/L", "value": _pnl_text(analysis, kind), "inline": True},
                    {"name": "Live", "value": current_text, "inline": False},
                    {"name": "Next step", "value": next_step, "inline": False},
                ],
                "footer": {"text": "MnT research-only position management · no order submitted"},
            }
        ],
    }


async def refresh_position_alerts(
    client: httpx.AsyncClient,
    state: PositionAlertState | None = None,
) -> dict[str, Any]:
    state = state or PositionAlertState()
    if not _enabled():
        return {"status": "disabled", "checked": 0, "sent": 0}

    base_url = os.getenv("MNT_DASHBOARD_API_URL", "http://127.0.0.1:8080").rstrip("/")
    webhook = os.getenv("MNT_DISCORD_WEBHOOK_URL", "").strip()
    positions = [
        item for item in list_focus_items()
        if str(item.get("kind") or "").upper() in {"OPEN_STOCK", "OPEN_OPTION"}
    ]
    results: list[dict[str, Any]] = []
    sent = 0

    for item in positions:
        symbol = str(item.get("symbol") or "").upper()
        kind = str(item.get("kind") or "").upper()
        endpoint = "option-analysis" if kind == "OPEN_OPTION" else "stock-analysis"
        row: dict[str, Any] = {"symbol": symbol, "kind": kind, "sent": False}
        try:
            response = await client.get(f"{base_url}/api/mnt/focus/{symbol}/{endpoint}", timeout=25.0)
            response.raise_for_status()
            analysis = response.json()
            management = analysis.get("management") if isinstance(analysis, dict) else {}
            current_state = str((management or {}).get("state") or "HOLD_WATCH").upper()
            transition = state.observe(symbol, kind, current_state)
            row.update(transition)
            if transition["notify"] and webhook:
                message = build_position_alert_message(
                    item=item,
                    analysis=analysis,
                    previous_state=transition.get("previous_state"),
                )
                alert_response = await client.post(webhook, json=message, timeout=20.0)
                alert_response.raise_for_status()
                row["sent"] = True
                sent += 1
        except Exception as exc:
            row["error"] = type(exc).__name__
        results.append(row)

    return {
        "status": "ok",
        "checked": len(positions),
        "sent": sent,
        "webhook_configured": bool(webhook),
        "positions": results,
    }
