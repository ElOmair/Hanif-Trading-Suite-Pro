from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from daily_scorecard import build_daily_scorecard

ET = ZoneInfo("America/New_York")
ROOT = Path(__file__).resolve().parent
DEFAULT_STATE = ROOT / "data" / "mnt_daily_scorecard_state.json"


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int, minimum: int = 0, maximum: int | None = None) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    value = max(minimum, value)
    return min(value, maximum) if maximum is not None else value


def state_path() -> Path:
    return Path(os.getenv("MNT_EOD_SCORECARD_STATE_FILE", str(DEFAULT_STATE))).expanduser()


def _load_state(path: Path | None = None) -> dict[str, Any]:
    path = path or state_path()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}


def _save_state(payload: dict[str, Any], path: Path | None = None) -> None:
    path = path or state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    temp.replace(path)


def due_for_delivery(now: datetime | None = None, state: dict[str, Any] | None = None) -> tuple[bool, str]:
    now_et = (now or datetime.now(ET)).astimezone(ET)
    session_date = now_et.date().isoformat()
    if now_et.weekday() >= 5:
        return False, session_date
    hour = _env_int("MNT_EOD_SCORECARD_HOUR_ET", 16, 0, 23)
    minute = _env_int("MNT_EOD_SCORECARD_MINUTE_ET", 15, 0, 59)
    if (now_et.hour, now_et.minute) < (hour, minute):
        return False, session_date
    state = state or {}
    return str(state.get("last_sent_session_date") or "") != session_date, session_date


def build_scorecard_message(scorecard: dict[str, Any]) -> dict[str, Any]:
    marks = scorecard.get("option_marks") or {}
    underlying = scorecard.get("underlying_outcomes") or {}
    best = scorecard.get("best_option") or {}
    worst = scorecard.get("worst_option") or {}
    quality = str(scorecard.get("quality_state") or "COLLECTING").upper()
    quality_emoji = {"STRONG": "🟢", "MIXED": "🟡", "WEAK": "🔴", "COLLECTING": "🔵"}.get(quality, "🔵")

    def pct(value: Any) -> str:
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return "—"
        return f"{parsed:+.1f}%"

    lines = [
        f"**Session quality:** {quality}",
        f"**READY ideas:** {int(scorecard.get('ready_ideas') or 0)} ({int(scorecard.get('long_ideas') or 0)} long / {int(scorecard.get('short_ideas') or 0)} short)",
        f"**Discord delivered:** {int(scorecard.get('discord_delivered') or 0)}",
        f"**Underlying target-first:** {underlying.get('wins', 0)}W / {underlying.get('losses', 0)}L" + (f" ({float(underlying['target_first_win_rate_pct']):.1f}%)" if underlying.get("target_first_win_rate_pct") is not None else ""),
        f"**{int(scorecard.get('option_horizon_minutes') or 60)}m option marks:** {int(marks.get('count') or 0)} · avg {pct(marks.get('average_return_pct'))} · positive {float(marks['positive_rate_pct']):.1f}%" if marks.get("positive_rate_pct") is not None else f"**{int(scorecard.get('option_horizon_minutes') or 60)}m option marks:** {int(marks.get('count') or 0)}",
    ]
    if best:
        lines.append(f"**Best:** {best.get('underlying') or '?'} {best.get('direction') or ''} · {pct(best.get('return_pct'))}")
    if worst:
        lines.append(f"**Worst:** {worst.get('underlying') or '?'} {worst.get('direction') or ''} · {pct(worst.get('return_pct'))}")
    lines.append(f"**Next session:** {scorecard.get('next_session_note') or 'Keep collecting shadow evidence.'}")
    lines.append("_Shadow/research scorecard only. No brokerage orders were placed by MnT._")
    return {
        "content": None,
        "embeds": [
            {
                "title": f"{quality_emoji} MnT Daily Scorecard · {scorecard.get('session_date_et') or ''}",
                "description": "\n".join(lines),
            }
        ],
    }


async def maybe_send_daily_scorecard(client: httpx.AsyncClient, now: datetime | None = None) -> dict[str, Any]:
    if not _env_bool("MNT_EOD_SCORECARD_ENABLED", False):
        return {"status": "disabled", "sent": False}
    webhook = os.getenv("MNT_DISCORD_WEBHOOK_URL", "").strip()
    if not webhook:
        return {"status": "webhook_missing", "sent": False}

    path = state_path()
    state = _load_state(path)
    due, session_date = due_for_delivery(now, state)
    if not due:
        return {"status": "not_due", "sent": False, "session_date_et": session_date}

    horizon = _env_int("MNT_DAILY_SCORECARD_OPTION_HORIZON", 60, 1)
    scorecard = build_daily_scorecard(session_date, option_horizon_minutes=horizon)
    response = await client.post(webhook, json=build_scorecard_message(scorecard), timeout=15.0)
    response.raise_for_status()
    sent_at = (now or datetime.now(ET)).astimezone(ET).isoformat()
    _save_state({"last_sent_session_date": session_date, "sent_at": sent_at}, path)
    return {
        "status": "sent",
        "sent": True,
        "session_date_et": session_date,
        "quality_state": scorecard.get("quality_state"),
        "ready_ideas": scorecard.get("ready_ideas"),
        "option_marks": (scorecard.get("option_marks") or {}).get("count"),
    }
