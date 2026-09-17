from __future__ import annotations

import os
import sqlite3
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo

from shadow_trade_store import DEFAULT_DB_PATH, list_shadow_trades

ET = ZoneInfo("America/New_York")
DEFAULT_HORIZONS = (15, 30, 60, 120)


def _db_path() -> Path:
    return Path(os.getenv("MNT_SHADOW_TRADE_DB", str(DEFAULT_DB_PATH))).expanduser()


def _number(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed == parsed else None


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def _connect() -> sqlite3.Connection:
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS mnt_option_shadow_marks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            shadow_trade_id INTEGER NOT NULL,
            signal_id INTEGER,
            option_symbol TEXT NOT NULL,
            horizon_minutes INTEGER NOT NULL,
            marked_at TEXT NOT NULL,
            actual_age_minutes REAL NOT NULL,
            lag_minutes REAL NOT NULL,
            entry_ask REAL,
            exit_bid REAL,
            exit_ask REAL,
            exit_mid REAL,
            return_bid_vs_entry_ask_pct REAL,
            return_mid_vs_entry_ask_pct REAL,
            quote_timestamp TEXT,
            feed TEXT,
            UNIQUE(shadow_trade_id, horizon_minutes)
        )
        """
    )
    connection.commit()
    return connection


def list_option_marks(
    shadow_trade_id: int | None = None,
    *,
    symbol: str | None = None,
    limit: int = 1000,
) -> list[dict[str, Any]]:
    limit = max(1, min(10000, int(limit)))
    with _connect() as connection:
        if shadow_trade_id is not None:
            rows = connection.execute(
                "SELECT * FROM mnt_option_shadow_marks WHERE shadow_trade_id = ? ORDER BY horizon_minutes",
                (int(shadow_trade_id),),
            ).fetchall()
        elif symbol:
            rows = connection.execute(
                """
                SELECT marks.*
                FROM mnt_option_shadow_marks AS marks
                JOIN mnt_shadow_trades AS trades ON trades.id = marks.shadow_trade_id
                WHERE trades.symbol = ?
                ORDER BY marks.id DESC
                LIMIT ?
                """,
                (symbol.strip().upper(), limit),
            ).fetchall()
        else:
            rows = connection.execute(
                "SELECT * FROM mnt_option_shadow_marks ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
    return [dict(row) for row in rows]


def due_option_marks(
    *,
    now: datetime | None = None,
    horizons: Iterable[int] = DEFAULT_HORIZONS,
    trade_limit: int = 500,
) -> list[dict[str, Any]]:
    """Return same-session shadow trades whose horizon mark is now due.

    A missed horizon is still eligible later in the same session. The stored
    `lag_minutes` makes delayed observations explicit so analysis can exclude
    them instead of pretending they were collected exactly on time.
    """
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    now_et = now.astimezone(ET)
    horizons = sorted({max(1, int(value)) for value in horizons})
    trades = list_shadow_trades(limit=trade_limit)

    with _connect() as connection:
        existing_rows = connection.execute(
            "SELECT shadow_trade_id, horizon_minutes FROM mnt_option_shadow_marks"
        ).fetchall()
    existing = {(int(row["shadow_trade_id"]), int(row["horizon_minutes"])) for row in existing_rows}

    due: list[dict[str, Any]] = []
    for trade in trades:
        trade_id = trade.get("id")
        option_symbol = str(trade.get("option_symbol") or "").strip().upper()
        entry_ask = _number(trade.get("option_ask"))
        created = _parse_time(trade.get("created_at"))
        if trade_id is None or not option_symbol or entry_ask is None or entry_ask <= 0 or created is None:
            continue
        created_et = created.astimezone(ET)
        if created_et.date() != now_et.date():
            continue
        age_minutes = (now - created).total_seconds() / 60.0
        if age_minutes < 0:
            continue
        for horizon in horizons:
            if age_minutes < horizon or (int(trade_id), horizon) in existing:
                continue
            due.append(
                {
                    "shadow_trade_id": int(trade_id),
                    "signal_id": trade.get("signal_id"),
                    "symbol": trade.get("symbol"),
                    "option_symbol": option_symbol,
                    "entry_ask": entry_ask,
                    "horizon_minutes": horizon,
                    "actual_age_minutes": round(age_minutes, 2),
                    "lag_minutes": round(max(0.0, age_minutes - horizon), 2),
                }
            )
    due.sort(key=lambda item: (item["lag_minutes"], item["horizon_minutes"], item["shadow_trade_id"]))
    return due


def record_option_mark(
    due: dict[str, Any],
    quote: dict[str, Any],
    *,
    marked_at: datetime | None = None,
    feed: str | None = None,
) -> int | None:
    marked_at = (marked_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    entry_ask = _number(due.get("entry_ask"))
    bid = _number(quote.get("bid") if "bid" in quote else quote.get("bp"))
    ask = _number(quote.get("ask") if "ask" in quote else quote.get("ap"))
    if entry_ask is None or entry_ask <= 0:
        return None
    mid = (bid + ask) / 2.0 if bid is not None and ask is not None and bid >= 0 and ask >= 0 else None
    conservative_return = ((bid / entry_ask) - 1.0) * 100.0 if bid is not None and bid >= 0 else None
    midpoint_return = ((mid / entry_ask) - 1.0) * 100.0 if mid is not None else None
    quote_timestamp = quote.get("timestamp") or quote.get("t")

    values = (
        int(due["shadow_trade_id"]),
        int(due["signal_id"]) if due.get("signal_id") is not None else None,
        str(due["option_symbol"]),
        int(due["horizon_minutes"]),
        marked_at.isoformat(),
        float(due["actual_age_minutes"]),
        float(due["lag_minutes"]),
        entry_ask,
        bid,
        ask,
        mid,
        conservative_return,
        midpoint_return,
        str(quote_timestamp) if quote_timestamp is not None else None,
        feed,
    )
    with _connect() as connection:
        connection.execute(
            """
            INSERT INTO mnt_option_shadow_marks(
                shadow_trade_id, signal_id, option_symbol, horizon_minutes,
                marked_at, actual_age_minutes, lag_minutes, entry_ask,
                exit_bid, exit_ask, exit_mid, return_bid_vs_entry_ask_pct,
                return_mid_vs_entry_ask_pct, quote_timestamp, feed
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(shadow_trade_id, horizon_minutes) DO NOTHING
            """,
            values,
        )
        row = connection.execute(
            "SELECT id FROM mnt_option_shadow_marks WHERE shadow_trade_id = ? AND horizon_minutes = ?",
            (int(due["shadow_trade_id"]), int(due["horizon_minutes"])),
        ).fetchone()
        connection.commit()
        return int(row["id"]) if row else None


def option_mark_summary(
    *,
    symbol: str | None = None,
    max_lag_minutes: float = 10.0,
    limit: int = 10000,
) -> dict[str, Any]:
    marks = list_option_marks(symbol=symbol, limit=limit)
    horizons: dict[str, Any] = {}
    for horizon in DEFAULT_HORIZONS:
        eligible = [
            row
            for row in marks
            if int(row.get("horizon_minutes") or 0) == horizon
            and _number(row.get("lag_minutes")) is not None
            and float(row["lag_minutes"]) <= float(max_lag_minutes)
            and _number(row.get("return_bid_vs_entry_ask_pct")) is not None
        ]
        returns = [float(row["return_bid_vs_entry_ask_pct"]) for row in eligible]
        winners = sum(1 for value in returns if value > 0)
        horizons[str(horizon)] = {
            "count": len(returns),
            "positive_count": winners,
            "positive_rate_pct": round(100.0 * winners / len(returns), 1) if returns else None,
            "average_return_pct": round(sum(returns) / len(returns), 2) if returns else None,
            "median_return_pct": round(statistics.median(returns), 2) if returns else None,
            "best_return_pct": round(max(returns), 2) if returns else None,
            "worst_return_pct": round(min(returns), 2) if returns else None,
            "gain_20pct_or_more_count": sum(1 for value in returns if value >= 20.0),
            "gain_50pct_or_more_count": sum(1 for value in returns if value >= 50.0),
            "gain_100pct_or_more_count": sum(1 for value in returns if value >= 100.0),
            "loss_25pct_or_worse_count": sum(1 for value in returns if value <= -25.0),
            "loss_50pct_or_worse_count": sum(1 for value in returns if value <= -50.0),
        }
    return {
        "symbol": symbol.strip().upper() if symbol else None,
        "marks_total": len(marks),
        "max_lag_minutes_in_summary": float(max_lag_minutes),
        "return_convention": "entry at surfaced ask; later mark at bid",
        "horizons": horizons,
        "note": "Shadow quote returns include bid/ask friction and do not represent an executed brokerage fill.",
    }
