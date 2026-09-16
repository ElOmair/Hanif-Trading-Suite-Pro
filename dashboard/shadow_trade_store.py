from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from signal_store import get_signal

ROOT = Path(__file__).resolve().parent
DEFAULT_DB_PATH = ROOT / "data" / "mnt_shadow_trades.sqlite3"


def _enabled() -> bool:
    return os.getenv("MNT_SHADOW_TRADES_ENABLED", "true").strip().lower() not in {"0", "false", "no", "off"}


def _db_path() -> Path:
    return Path(os.getenv("MNT_SHADOW_TRADE_DB", str(DEFAULT_DB_PATH))).expanduser()


def _number(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed == parsed else None


def _connect() -> sqlite3.Connection:
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS mnt_shadow_trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            signal_id INTEGER UNIQUE,
            created_at TEXT NOT NULL,
            symbol TEXT NOT NULL,
            direction TEXT,
            fusion_score REAL,
            coverage_pct REAL,
            stock_price REAL,
            entry_low REAL,
            entry_high REAL,
            stop_price REAL,
            target1 REAL,
            option_symbol TEXT,
            option_strike REAL,
            option_expiration TEXT,
            option_bid REAL,
            option_ask REAL,
            discord_sent INTEGER NOT NULL DEFAULT 0,
            payload_json TEXT NOT NULL
        )
        """
    )
    connection.commit()
    return connection


def _pick(mapping: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = mapping.get(key)
        if value not in (None, ""):
            return value
    return None


def record_ready_shadow_trade(payload: dict[str, Any], *, discord_sent: bool = False) -> int | None:
    """Record what a READY alert would have exposed, without placing an order."""
    if not _enabled():
        return None
    gate = payload.get("execution_gate") or {}
    if gate.get("entry_review_allowed") is not True and str(gate.get("state") or "").upper() != "REVIEW_ENTRY":
        return None

    symbol = str(payload.get("symbol") or "").upper()
    if not symbol:
        return None
    fusion = payload.get("fusion_score") or {}
    technical = payload.get("technical") or {}
    plan = payload.get("trade_plan") or {}
    options = payload.get("options") or []
    option = options[0] if isinstance(options, list) and options and isinstance(options[0], dict) else {}
    signal_id_raw = payload.get("signal_id") or payload.get("deduplicated_signal_id")
    try:
        signal_id = int(signal_id_raw) if signal_id_raw is not None else None
    except (TypeError, ValueError):
        signal_id = None

    created_at = datetime.now(timezone.utc).isoformat()
    encoded = json.dumps(payload, default=str, separators=(",", ":"))
    values = (
        signal_id,
        created_at,
        symbol,
        str(fusion.get("direction") or technical.get("signal") or "").upper() or None,
        _number(fusion.get("score")),
        _number(fusion.get("coverage_pct")),
        _number(technical.get("price")),
        _number(_pick(plan, "entry_low", "entryLow") or technical.get("entry_low")),
        _number(_pick(plan, "entry_high", "entryHigh") or technical.get("entry_high")),
        _number(_pick(plan, "stop", "stop_price", "stopLevel")),
        _number(_pick(plan, "tp1", "target1", "target_1")),
        str(_pick(option, "symbol", "contract_symbol", "option_symbol") or "") or None,
        _number(_pick(option, "strike", "strike_price")),
        str(_pick(option, "expiration", "expiry", "expiration_date") or "") or None,
        _number(_pick(option, "bid", "bid_price")),
        _number(_pick(option, "ask", "ask_price")),
        1 if discord_sent else 0,
        encoded,
    )

    with _connect() as connection:
        if signal_id is not None:
            connection.execute(
                """
                INSERT INTO mnt_shadow_trades(
                    signal_id, created_at, symbol, direction, fusion_score, coverage_pct,
                    stock_price, entry_low, entry_high, stop_price, target1,
                    option_symbol, option_strike, option_expiration, option_bid, option_ask,
                    discord_sent, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(signal_id) DO UPDATE SET
                    discord_sent = MAX(mnt_shadow_trades.discord_sent, excluded.discord_sent),
                    payload_json = excluded.payload_json
                """,
                values,
            )
            row = connection.execute("SELECT id FROM mnt_shadow_trades WHERE signal_id = ?", (signal_id,)).fetchone()
            connection.commit()
            return int(row["id"]) if row else None

        cursor = connection.execute(
            """
            INSERT INTO mnt_shadow_trades(
                signal_id, created_at, symbol, direction, fusion_score, coverage_pct,
                stock_price, entry_low, entry_high, stop_price, target1,
                option_symbol, option_strike, option_expiration, option_bid, option_ask,
                discord_sent, payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            values,
        )
        connection.commit()
        return int(cursor.lastrowid)


def list_shadow_trades(symbol: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    if not _enabled():
        return []
    limit = max(1, min(5000, int(limit)))
    with _connect() as connection:
        if symbol:
            rows = connection.execute(
                "SELECT * FROM mnt_shadow_trades WHERE symbol = ? ORDER BY id DESC LIMIT ?",
                (symbol.strip().upper(), limit),
            ).fetchall()
        else:
            rows = connection.execute("SELECT * FROM mnt_shadow_trades ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [dict(row) for row in rows]


def shadow_trade_summary(
    symbol: str | None = None,
    limit: int = 1000,
    *,
    signal_lookup: Callable[[int], dict[str, Any] | None] | None = None,
) -> dict[str, Any]:
    lookup = signal_lookup or get_signal
    trades = list_shadow_trades(symbol=symbol, limit=limit)
    wins = losses = ambiguous = pending = 0
    delivered = 0
    for trade in trades:
        delivered += int(bool(trade.get("discord_sent")))
        signal_id = trade.get("signal_id")
        if signal_id is None:
            pending += 1
            continue
        signal = lookup(int(signal_id))
        outcome = (signal or {}).get("outcome") or {}
        label = str(outcome.get("calibration_label") or "").upper()
        if label == "WIN":
            wins += 1
        elif label == "LOSS":
            losses += 1
        elif label == "AMBIGUOUS":
            ambiguous += 1
        else:
            pending += 1

    resolved = wins + losses
    return {
        "symbol": symbol.strip().upper() if symbol else None,
        "shadow_trades": len(trades),
        "discord_delivered": delivered,
        "resolved": resolved,
        "wins": wins,
        "losses": losses,
        "ambiguous": ambiguous,
        "pending": pending,
        "target_first_win_rate_pct": round(100.0 * wins / resolved, 1) if resolved else None,
        "mode": "shadow only; no brokerage order is placed",
        "note": "Outcomes are linked to the same persisted Fusion signals used by MnT calibration.",
    }
