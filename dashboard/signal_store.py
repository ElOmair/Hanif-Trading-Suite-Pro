from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from risk_governor import build_execution_gate

DEFAULT_DB = Path(__file__).resolve().parent / "data" / "mnt_signals.sqlite3"


def _enabled() -> bool:
    return os.getenv("MNT_SIGNAL_DB_ENABLED", "true").strip().lower() not in {"0", "false", "no", "off"}


def _env_float(name: str, default: float, minimum: float = 0.0) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(minimum, value)


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
            payload_json TEXT NOT NULL,
            outcome_status TEXT,
            evaluated_at TEXT,
            outcome_json TEXT
        )
        """
    )
    existing = {row[1] for row in connection.execute("PRAGMA table_info(mnt_signals)").fetchall()}
    migrations = {
        "outcome_status": "ALTER TABLE mnt_signals ADD COLUMN outcome_status TEXT",
        "evaluated_at": "ALTER TABLE mnt_signals ADD COLUMN evaluated_at TEXT",
        "outcome_json": "ALTER TABLE mnt_signals ADD COLUMN outcome_json TEXT",
    }
    for column, sql in migrations.items():
        if column not in existing:
            connection.execute(sql)
    connection.execute("CREATE INDEX IF NOT EXISTS idx_mnt_signals_symbol_created ON mnt_signals(symbol, created_at DESC)")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_mnt_signals_outcome_status ON mnt_signals(outcome_status)")
    return connection


def _decision_label(value: Any) -> str | None:
    if isinstance(value, dict):
        for key in ("decision", "action", "state", "status"):
            if value.get(key):
                return str(value[key]).upper()
    if value is None:
        return None
    return str(value).upper()


def _number(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed == parsed else None


def _attach_execution_gate(payload: dict[str, Any]) -> None:
    if isinstance(payload.get("execution_gate"), dict):
        return
    try:
        payload["execution_gate"] = build_execution_gate(
            technical=payload.get("technical") or {},
            fusion_score=payload.get("fusion_score") or {},
            decision=payload.get("decision"),
            trade_plan=payload.get("trade_plan") or {},
            market_gate=payload.get("market_gate") or {},
        )
    except Exception as exc:
        payload["execution_gate"] = {
            "state": "BLOCKED",
            "entry_review_allowed": False,
            "order_authorized": False,
            "research_only": True,
            "primary_reason": "The MnT risk governor could not evaluate this setup.",
            "error": type(exc).__name__,
        }


def _decode_row(row: sqlite3.Row) -> dict[str, Any]:
    item = dict(row)
    try:
        item["payload"] = json.loads(item.pop("payload_json"))
    except Exception:
        item["payload"] = None
        item.pop("payload_json", None)
    raw_outcome = item.pop("outcome_json", None)
    if raw_outcome:
        try:
            item["outcome"] = json.loads(raw_outcome)
        except Exception:
            item["outcome"] = None
    else:
        item["outcome"] = None
    return item


def _recent_duplicate(
    connection: sqlite3.Connection,
    *,
    symbol: str,
    direction: str | None,
    decision: str | None,
    score: float | None,
    now: datetime,
) -> sqlite3.Row | None:
    window_minutes = _env_float("MNT_SIGNAL_DEDUPE_MINUTES", 5.0, 0.0)
    score_delta = _env_float("MNT_SIGNAL_DEDUPE_SCORE_DELTA", 3.0, 0.0)
    if window_minutes <= 0 or not symbol:
        return None

    row = connection.execute(
        """
        SELECT id, created_at, score, direction, decision
        FROM mnt_signals
        WHERE symbol = ?
          AND COALESCE(direction, '') = COALESCE(?, '')
          AND COALESCE(decision, '') = COALESCE(?, '')
        ORDER BY id DESC
        LIMIT 1
        """,
        (symbol, direction, decision),
    ).fetchone()
    if row is None:
        return None

    try:
        prior_time = datetime.fromisoformat(str(row["created_at"]).replace("Z", "+00:00"))
        if prior_time.tzinfo is None:
            prior_time = prior_time.replace(tzinfo=timezone.utc)
        prior_time = prior_time.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None

    age_minutes = (now - prior_time).total_seconds() / 60.0
    if age_minutes < 0 or age_minutes > window_minutes:
        return None

    prior_score = _number(row["score"])
    scores_close = (
        score is None and prior_score is None
        or score is not None and prior_score is not None and abs(score - prior_score) <= score_delta
    )
    return row if scores_close else None


def record_signal(payload: dict[str, Any]) -> int | None:
    # Fusion returns the same mutable payload after this call, so attaching the
    # gate here gives every response the server-side verdict even if persistence
    # is disabled. The database is only the persistence layer, not the gate.
    _attach_execution_gate(payload)
    if not _enabled():
        return None

    fusion = payload.get("fusion_score") or {}
    symbol = str(payload.get("symbol") or "").upper()
    direction = str(fusion.get("direction") or "").upper() or None
    score = _number(fusion.get("score"))
    decision = _decision_label(payload.get("decision"))
    now = datetime.now(timezone.utc)
    created_at = now.isoformat()

    with _connect() as connection:
        duplicate = _recent_duplicate(
            connection,
            symbol=symbol,
            direction=direction,
            decision=decision,
            score=score,
            now=now,
        )
        if duplicate is not None:
            existing_id = int(duplicate["id"])
            payload["signal_deduplicated"] = True
            payload["deduplicated_signal_id"] = existing_id
            payload["dedupe_reason"] = "Same symbol, direction, decision, and materially similar score within the dedupe window."
            return existing_id

        payload["signal_deduplicated"] = False
        encoded = json.dumps(payload, default=str, separators=(",", ":"))
        cursor = connection.execute(
            """
            INSERT INTO mnt_signals(
                created_at, symbol, direction, score, coverage_pct, grade,
                beginner_state, decision, payload_json, outcome_status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                created_at,
                symbol,
                direction,
                score,
                fusion.get("coverage_pct"),
                fusion.get("grade"),
                fusion.get("beginner_state"),
                decision,
                encoded,
                "PENDING",
            ),
        )
        return int(cursor.lastrowid)


def get_signal(signal_id: int) -> dict[str, Any] | None:
    if not _enabled():
        return None
    with _connect() as connection:
        row = connection.execute("SELECT * FROM mnt_signals WHERE id = ?", (int(signal_id),)).fetchone()
    return _decode_row(row) if row else None


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
    return [_decode_row(row) for row in rows]


def list_pending_signals(symbol: str | None = None, limit: int = 500) -> list[dict[str, Any]]:
    if not _enabled():
        return []
    limit = max(1, min(2000, int(limit)))
    with _connect() as connection:
        if symbol:
            rows = connection.execute(
                """
                SELECT * FROM mnt_signals
                WHERE symbol = ? AND COALESCE(outcome_status, 'PENDING') IN ('PENDING', 'EVALUATED_1H')
                ORDER BY id ASC LIMIT ?
                """,
                (symbol.strip().upper(), limit),
            ).fetchall()
        else:
            rows = connection.execute(
                """
                SELECT * FROM mnt_signals
                WHERE COALESCE(outcome_status, 'PENDING') IN ('PENDING', 'EVALUATED_1H')
                ORDER BY id ASC LIMIT ?
                """,
                (limit,),
            ).fetchall()
    return [_decode_row(row) for row in rows]


def update_signal_outcome(signal_id: int, outcome: dict[str, Any], status: str) -> bool:
    if not _enabled():
        return False
    evaluated_at = datetime.now(timezone.utc).isoformat()
    encoded = json.dumps(outcome, default=str, separators=(",", ":"))
    with _connect() as connection:
        cursor = connection.execute(
            """
            UPDATE mnt_signals
            SET outcome_status = ?, evaluated_at = ?, outcome_json = ?
            WHERE id = ?
            """,
            (str(status).upper(), evaluated_at, encoded, int(signal_id)),
        )
        return cursor.rowcount > 0


def calibration_summary(symbol: str | None = None, limit: int = 1000) -> dict[str, Any]:
    rows = list_signals(symbol=symbol, limit=limit)
    evaluated = [
        row
        for row in rows
        if row.get("outcome_status") in {"EVALUATED_1H", "EVALUATED_2H"}
        and str(row.get("direction") or "").upper() in {"LONG", "SHORT"}
        and isinstance(row.get("outcome"), dict)
    ]
    buckets: dict[str, dict[str, Any]] = {}
    for row in evaluated:
        score = row.get("score")
        outcome = row.get("outcome") or {}
        label = str(outcome.get("calibration_label") or "UNRESOLVED").upper()
        try:
            score_value = float(score)
        except (TypeError, ValueError):
            continue
        lower = int(score_value // 10) * 10
        upper = min(100, lower + 9)
        key = f"{lower}-{upper}"
        bucket = buckets.setdefault(
            key,
            {
                "count": 0,
                "wins": 0,
                "losses": 0,
                "ambiguous": 0,
                "unresolved": 0,
                "positive_2h": 0,
                "negative_2h": 0,
            },
        )
        bucket["count"] += 1
        if label == "WIN":
            bucket["wins"] += 1
        elif label == "LOSS":
            bucket["losses"] += 1
        elif label == "AMBIGUOUS":
            bucket["ambiguous"] += 1
        else:
            bucket["unresolved"] += 1
        directional_2h = _number(outcome.get("directional_return_2h_pct"))
        if directional_2h is not None:
            if directional_2h > 0:
                bucket["positive_2h"] += 1
            elif directional_2h < 0:
                bucket["negative_2h"] += 1

    for bucket in buckets.values():
        resolved = bucket["wins"] + bucket["losses"]
        bucket["target_first_win_rate_pct"] = round(100.0 * bucket["wins"] / resolved, 1) if resolved else None
        directional = bucket["positive_2h"] + bucket["negative_2h"]
        bucket["positive_2h_rate_pct"] = round(100.0 * bucket["positive_2h"] / directional, 1) if directional else None

    return {
        "symbol": symbol.strip().upper() if symbol else None,
        "evaluated_count": len(evaluated),
        "total_count": len(rows),
        "score_buckets": buckets,
        "note": "Calibration includes only gradable LONG/SHORT signals. It is descriptive signal history, not a guarantee of future performance.",
    }
