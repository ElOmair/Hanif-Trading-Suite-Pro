from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_DB = Path(__file__).resolve().parent / "data" / "mnt_signals.sqlite3"


def _enabled() -> bool:
    return os.getenv("MNT_SIGNAL_DB_ENABLED", "true").strip().lower() not in {"0", "false", "no", "off"}


def _path() -> Path:
    return Path(os.getenv("MNT_SIGNAL_DB", str(DEFAULT_DB))).expanduser()


def _connect() -> sqlite3.Connection:
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=5)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA synchronous=NORMAL")
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS mnt_signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            symbol TEXT NOT NULL,
            direction TEXT,
            score REAL,
            coverage_pct REAL,
            grade TEXT,
            beginner_state TEXT,
            decision TEXT,
            payload_json TEXT NOT NULL
        )
        """
    )
    connection.execute("CREATE INDEX IF NOT EXISTS idx_mnt_signals_symbol_created ON mnt_signals(symbol, created_at DESC)")
    return connection


def _decision_label(value: Any) -> str | None:
    if isinstance(value, dict):
        for key in ("decision", "action", "state", "status"):
            if value.get(key):
                return str(value[key]).upper()
    if value is None:
        return None
    return str(value).upper()


def record_signal(payload: dict[str, Any]) -> int | None:
    if not _enabled():
        return None
    fusion = payload.get("fusion_score") or {}
    created_at = datetime.now(timezone.utc).isoformat()
    encoded = json.dumps(payload, default=str, separators=(",", ":"))
    with _connect() as connection:
        cursor = connection.execute(
            """
            INSERT INTO mnt_signals(
                created_at, symbol, direction, score, coverage_pct, grade,
                beginner_state, decision, payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                created_at,
                str(payload.get("symbol") or "").upper(),
                fusion.get("direction"),
                fusion.get("score"),
                fusion.get("coverage_pct"),
                fusion.get("grade"),
                fusion.get("beginner_state"),
                _decision_label(payload.get("decision")),
                encoded,
            ),
        )
        return int(cursor.lastrowid)


def list_signals(symbol: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    if not _enabled():
        return []
    limit = max(1, min(500, int(limit)))
    with _connect() as connection:
        if symbol:
            rows = connection.execute(
                "SELECT * FROM mnt_signals WHERE symbol = ? ORDER BY id DESC LIMIT ?",
                (symbol.strip().upper(), limit),
            ).fetchall()
        else:
            rows = connection.execute("SELECT * FROM mnt_signals ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    results = []
    for row in rows:
        item = dict(row)
        try:
            item["payload"] = json.loads(item.pop("payload_json"))
        except Exception:
            item["payload"] = None
            item.pop("payload_json", None)
        results.append(item)
    return results
