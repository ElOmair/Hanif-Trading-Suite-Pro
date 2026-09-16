from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import pandas as pd

from signal_store import list_pending_signals, update_signal_outcome


def _number(value: Any) -> float | None:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if value == value else None


def _timestamp_series(frame: pd.DataFrame) -> pd.Series:
    """Return bar timestamps normalized to UTC.

    Kronos/Alpaca CSV files may contain either epoch timestamps, ISO timestamps
    with an explicit offset, or naive market-clock timestamps. Naive values are
    interpreted in MNT_BAR_TIMEZONE (America/New_York by default) before being
    converted to UTC so outcome grading lines up with the UTC signal timestamp.
    """
    for name in ("timestamps", "timestamp", "datetime", "time", "date"):
        if name not in frame.columns:
            continue

        raw = frame[name]
        if pd.api.types.is_numeric_dtype(raw):
            sample = pd.to_numeric(raw, errors="coerce").dropna()
            unit = "ms" if not sample.empty and float(sample.abs().median()) > 10_000_000_000 else "s"
            return pd.to_datetime(raw, errors="coerce", utc=True, unit=unit)

        text = raw.astype("string").str.strip()
        # Explicit offsets/Z can be safely normalized directly to UTC. This also
        # handles rows spanning EST/EDT without creating mixed-timezone objects.
        explicit_zone = text.str.contains(r"(?:Z|[+-]\d{2}:?\d{2})$", regex=True, na=False)
        if bool(explicit_zone.any()):
            return pd.to_datetime(raw, errors="coerce", utc=True, format="mixed")

        parsed = pd.to_datetime(raw, errors="coerce", format="mixed")
        timezone_name = os.getenv("MNT_BAR_TIMEZONE", "America/New_York").strip() or "America/New_York"
        try:
            localized = parsed.dt.tz_localize(timezone_name, ambiguous="NaT", nonexistent="shift_forward")
            return localized.dt.tz_convert("UTC")
        except (AttributeError, TypeError, ValueError):
            # Last-resort normalization for uncommon timestamp shapes. Returning
            # NaT is safer than silently grading a signal against the wrong bars.
            values: list[pd.Timestamp | pd.NaTType] = []
            for value in parsed:
                if pd.isna(value):
                    values.append(pd.NaT)
                    continue
                stamp = pd.Timestamp(value)
                try:
                    if stamp.tzinfo is None:
                        stamp = stamp.tz_localize(timezone_name, ambiguous="NaT", nonexistent="shift_forward")
                    values.append(stamp.tz_convert("UTC"))
                except (TypeError, ValueError):
                    values.append(pd.NaT)
            return pd.Series(values, index=frame.index, dtype="datetime64[ns, UTC]")

    return pd.Series(pd.NaT, index=frame.index, dtype="datetime64[ns, UTC]")


def _extract_plan(payload: dict[str, Any]) -> tuple[float | None, float | None, float | None]:
    technical = payload.get("technical") or {}
    plan = payload.get("trade_plan") or {}
    entry = _number(plan.get("entry") or plan.get("entry_price") or technical.get("price"))
    target = _number(plan.get("tp1") or plan.get("target1") or plan.get("target_1"))
    stop = _number(plan.get("stop") or plan.get("stop_price") or plan.get("stopLevel"))
    return entry, target, stop


def evaluate_signal_row(signal: dict[str, Any], frame: pd.DataFrame) -> tuple[str, dict[str, Any]]:
    payload = signal.get("payload") or {}
    direction = str(signal.get("direction") or (payload.get("fusion_score") or {}).get("direction") or "").upper()
    if direction not in {"LONG", "SHORT"}:
        return "UNSCORABLE", {"calibration_label": "UNRESOLVED", "reason": "Signal direction was not LONG or SHORT."}

    created_at = pd.to_datetime(signal.get("created_at"), errors="coerce", utc=True)
    if pd.isna(created_at):
        return "UNSCORABLE", {"calibration_label": "UNRESOLVED", "reason": "Signal timestamp could not be parsed."}

    data = frame.copy()
    for col in ("open", "high", "low", "close"):
        if col not in data.columns:
            return "UNSCORABLE", {"calibration_label": "UNRESOLVED", "reason": f"Missing {col} column."}
        data[col] = pd.to_numeric(data[col], errors="coerce")
    data["_ts"] = _timestamp_series(data)
    data = data.dropna(subset=["_ts", "open", "high", "low", "close"]).sort_values("_ts")
    future = data.loc[data["_ts"] > created_at].head(24).reset_index(drop=True)
    if len(future) < 12:
        return "PENDING", {
            "calibration_label": "UNRESOLVED",
            "bars_available": len(future),
            "bars_needed_for_1h": 12,
        }

    entry, target, stop = _extract_plan(payload)
    if entry is None:
        entry = float(future.iloc[0]["open"])

    sign = 1.0 if direction == "LONG" else -1.0
    first_12 = future.iloc[:12]
    end_1h = float(first_12.iloc[-1]["close"])
    directional_1h = sign * (end_1h / entry - 1.0) * 100.0

    end_2h = None
    directional_2h = None
    if len(future) >= 24:
        end_2h = float(future.iloc[23]["close"])
        directional_2h = sign * (end_2h / entry - 1.0) * 100.0

    eval_window = future.iloc[:24] if len(future) >= 24 else future
    if direction == "LONG":
        mfe = (float(eval_window["high"].max()) / entry - 1.0) * 100.0
        mae = (float(eval_window["low"].min()) / entry - 1.0) * 100.0
    else:
        mfe = (1.0 - float(eval_window["low"].min()) / entry) * 100.0
        mae = (1.0 - float(eval_window["high"].max()) / entry) * 100.0

    first_hit = "NONE"
    target_hit_at = None
    stop_hit_at = None
    if target is not None or stop is not None:
        for _, bar in eval_window.iterrows():
            high = float(bar["high"])
            low = float(bar["low"])
            target_hit = False
            stop_hit = False
            if target is not None:
                target_hit = high >= target if direction == "LONG" else low <= target
            if stop is not None:
                stop_hit = low <= stop if direction == "LONG" else high >= stop
            if target_hit and target_hit_at is None:
                target_hit_at = bar["_ts"].isoformat()
            if stop_hit and stop_hit_at is None:
                stop_hit_at = bar["_ts"].isoformat()
            if target_hit and stop_hit:
                first_hit = "AMBIGUOUS_SAME_BAR"
                break
            if target_hit:
                first_hit = "TARGET_FIRST"
                break
            if stop_hit:
                first_hit = "STOP_FIRST"
                break

    calibration_label = "UNRESOLVED"
    if first_hit == "TARGET_FIRST":
        calibration_label = "WIN"
    elif first_hit == "STOP_FIRST":
        calibration_label = "LOSS"
    elif first_hit == "AMBIGUOUS_SAME_BAR":
        calibration_label = "AMBIGUOUS"

    status = "EVALUATED_2H" if len(future) >= 24 else "EVALUATED_1H"
    return status, {
        "calibration_label": calibration_label,
        "direction": direction,
        "entry_price": round(entry, 6),
        "target1": target,
        "stop": stop,
        "first_hit": first_hit,
        "target_hit_at": target_hit_at,
        "stop_hit_at": stop_hit_at,
        "directional_return_1h_pct": round(directional_1h, 4),
        "directional_return_2h_pct": round(directional_2h, 4) if directional_2h is not None else None,
        "mfe_pct": round(mfe, 4),
        "mae_pct": round(mae, 4),
        "bars_evaluated": len(eval_window),
        "end_1h_price": round(end_1h, 6),
        "end_2h_price": round(end_2h, 6) if end_2h is not None else None,
    }


def calibrate_symbol_signals(symbol: str, data_dir: Path) -> dict[str, Any]:
    symbol = symbol.strip().upper()
    csv_path = Path(data_dir) / f"{symbol}_5m.csv"
    if not csv_path.exists():
        return {"symbol": symbol, "evaluated": 0, "pending": 0, "status": "missing_bars"}

    frame = pd.read_csv(csv_path)
    rows = list_pending_signals(symbol=symbol, limit=1000)
    evaluated = 0
    pending = 0
    unscorable = 0
    for row in rows:
        status, outcome = evaluate_signal_row(row, frame)
        if status == "PENDING":
            pending += 1
            continue
        if status == "UNSCORABLE":
            unscorable += 1
        else:
            evaluated += 1
        update_signal_outcome(int(row["id"]), outcome, status)

    return {
        "symbol": symbol,
        "evaluated": evaluated,
        "pending": pending,
        "unscorable": unscorable,
        "status": "ok",
    }
