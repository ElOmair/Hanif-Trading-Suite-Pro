from __future__ import annotations

import asyncio
import dataclasses
import importlib
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd
from fastapi import APIRouter, HTTPException, Query

from gamma_provider import fetch_gamma_context
from mnt_engine import build_fusion_score
from signal_store import list_signals, record_signal

router = APIRouter(prefix="/api/kronos", tags=["kronos"])

KRONOS_ROOT = Path(os.getenv("KRONOS_ROOT", "/home/airomair/Kronos"))
ENSEMBLE_SCRIPT = KRONOS_ROOT / "trading" / "ensemble_forecast.py"
MARKET_DATA_SCRIPT = KRONOS_ROOT / "trading" / "market_data.py"
DATA_DIR = KRONOS_ROOT / "trading" / "data"
SYMBOL_RE = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")
ET = ZoneInfo("America/New_York")
_analysis_lock = asyncio.Lock()


def _number(pattern: str, text: str) -> float | None:
    match = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
    return float(match.group(1)) if match else None


def _integer_pair(pattern: str, text: str) -> tuple[int, int] | None:
    match = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
    return (int(match.group(1)), int(match.group(2))) if match else None


def _word(pattern: str, text: str) -> str | None:
    match = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
    return match.group(1).strip().upper() if match else None


def _jsonable(value: Any) -> Any:
    if dataclasses.is_dataclass(value):
        return _jsonable(dataclasses.asdict(value))
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(v) for v in value]
    if hasattr(value, "model_dump"):
        return _jsonable(value.model_dump())
    if hasattr(value, "__dict__") and not isinstance(value, type):
        return _jsonable(vars(value))
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _opening_market_gate() -> dict[str, Any]:
    now = datetime.now(ET)
    seconds_from_midnight = now.hour * 3600 + now.minute * 60 + now.second
    start = 9 * 3600 + 30 * 60
    end = 9 * 3600 + 35 * 60
    active = now.weekday() < 5 and start <= seconds_from_midnight < end
    return {
        "active": active,
        "state": "OPENING_LOCKOUT" if active else "NORMAL",
        "et_time": now.isoformat(),
        "lockout_start_et": "09:30:00",
        "lockout_end_et": "09:35:00",
        "reason": (
            "The first 5-minute regular-session candle is still developing. "
            "Kronos forecast data is informational only; CONFIRM, trade plans, and option scans are locked until 09:35 ET."
            if active
            else None
        ),
    }


def _parse_output(symbol: str, output: str) -> dict[str, Any]:
    bullish = _integer_pair(r"Bullish paths:\s*(\d+)\s*/\s*(\d+)", output)
    bearish = _integer_pair(r"Bearish paths:\s*(\d+)\s*/\s*(\d+)", output)
    neutral = _integer_pair(r"Neutral paths:\s*(\d+)\s*/\s*(\d+)", output)

    result: dict[str, Any] = {
        "symbol": symbol,
        "average_score": _number(r"Average score:\s*([+-]?\d+(?:\.\d+)?)", output),
        "median_1h_move_pct": _number(r"Median 1H move:\s*([+-]?\d+(?:\.\d+)?)%", output),
        "median_2h_move_pct": _number(r"Median 2H move:\s*([+-]?\d+(?:\.\d+)?)%", output),
        "score_spread": _number(r"Score spread:\s*([+-]?\d+(?:\.\d+)?)", output),
        "score_std_dev": _number(r"Score std dev:\s*([+-]?\d+(?:\.\d+)?)", output),
        "bias_agreement_pct": _number(r"Bias agreement:\s*([+-]?\d+(?:\.\d+)?)%", output),
        "stability": _word(r"Stability:\s*([A-Za-z]+)", output),
        "final_bias": _word(r"FINAL BIAS:\s*([A-Za-z]+)", output),
        "action": _word(r"ACTION:\s*([A-Za-z]+)", output),
        "runtime_seconds": _number(r"Runtime:\s*([+-]?\d+(?:\.\d+)?)\s*sec", output),
        "peak_gpu_vram_mb": _number(r"Peak GPU VRAM:\s*([+-]?\d+(?:\.\d+)?)\s*MB", output),
        "source": "Kronos ensemble_forecast.py",
        "research_only": True,
    }
    if bullish:
        result["bullish_paths"], result["path_count"] = bullish
    if bearish:
        result["bearish_paths"] = bearish[0]
        result.setdefault("path_count", bearish[1])
    if neutral:
        result["neutral_paths"] = neutral[0]
        result.setdefault("path_count", neutral[1])
    return result


async def _run_script(script: Path, symbol: str, timeout: float) -> tuple[int, str]:
    env = os.environ.copy()
    env.setdefault("PYTHONUNBUFFERED", "1")
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        str(script),
        symbol,
        cwd=str(KRONOS_ROOT),
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    try:
        stdout, _ = await asyncio.wait_for(process.communicate(), timeout=timeout)
    except TimeoutError:
        process.kill()
        await process.communicate()
        raise HTTPException(status_code=504, detail=f"{script.name} timed out")
    return process.returncode or 0, stdout.decode("utf-8", errors="replace")


async def run_kronos_analysis(symbol: str) -> dict[str, Any]:
    symbol = symbol.strip().upper()
    if not SYMBOL_RE.fullmatch(symbol):
        raise HTTPException(status_code=400, detail="Invalid symbol")
    if not MARKET_DATA_SCRIPT.exists():
        raise HTTPException(status_code=503, detail=f"Kronos market-data script not found at {MARKET_DATA_SCRIPT}")
    if not ENSEMBLE_SCRIPT.exists():
        raise HTTPException(status_code=503, detail=f"Kronos ensemble script not found at {ENSEMBLE_SCRIPT}")

    async with _analysis_lock:
        market_code, market_output = await _run_script(MARKET_DATA_SCRIPT, symbol, 30)
        if market_code != 0:
            tail = "\n".join(market_output.strip().splitlines()[-12:])
            raise HTTPException(status_code=502, detail=f"Market data refresh failed:\n{tail}")

        code, output = await _run_script(ENSEMBLE_SCRIPT, symbol, 45)
        if code != 0:
            tail = "\n".join(output.strip().splitlines()[-12:])
            raise HTTPException(status_code=502, detail=f"Kronos forecast failed:\n{tail}")

    parsed = _parse_output(symbol, output)
    if parsed.get("final_bias") is None:
        tail = "\n".join(output.strip().splitlines()[-20:])
        raise HTTPException(status_code=502, detail=f"Kronos output could not be parsed:\n{tail}")
    parsed["market_data_refreshed"] = True
    return parsed


def _directional_features(symbol: str) -> dict[str, Any]:
    csv_path = DATA_DIR / f"{symbol}_5m.csv"
    if not csv_path.exists():
        raise HTTPException(status_code=503, detail=f"Technical data missing for {symbol}")

    frame = pd.read_csv(csv_path)
    if len(frame) < 30:
        raise HTTPException(status_code=503, detail=f"Not enough 5m data for {symbol}")

    frame = frame.tail(160).copy()
    for col in ("open", "high", "low", "close", "volume"):
        frame[col] = pd.to_numeric(frame[col], errors="coerce")
    frame = frame.dropna(subset=["open", "high", "low", "close", "volume"])
    close = frame["close"]
    high = frame["high"]
    low = frame["low"]
    volume = frame["volume"]
    ema9 = close.ewm(span=9, adjust=False).mean()
    ema21 = close.ewm(span=21, adjust=False).mean()
    prev_close = close.shift(1)
    tr = pd.concat([(high - low), (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
    atr = float(tr.tail(14).mean())
    last = float(close.iloc[-1])
    momentum = float((last / close.iloc[-7] - 1) * 100) if len(close) >= 7 else 0.0
    avg_vol = float(volume.iloc[-21:-1].mean()) if len(volume) >= 21 else float(volume.iloc[:-1].mean())
    rvol = float(volume.iloc[-1] / avg_vol) if avg_vol > 0 else 0.0
    ema_spread = float((ema9.iloc[-1] / ema21.iloc[-1] - 1) * 100) if ema21.iloc[-1] else 0.0

    score = 50.0 + max(-18.0, min(18.0, ema_spread * 45.0)) + max(-18.0, min(18.0, momentum * 9.0))
    if rvol >= 1.5:
        score += 8.0 if momentum >= 0 else -8.0
    elif rvol >= 1.1:
        score += 4.0 if momentum >= 0 else -4.0
    score = max(0.0, min(100.0, score))
    signal = "LONG" if score >= 62 else "SHORT" if score <= 38 else "NEUTRAL"

    prior20_high = float(high.iloc[-21:-1].max())
    prior20_low = float(low.iloc[-21:-1].min())
    bos = "bullish" if last > prior20_high else "bearish" if last < prior20_low else "neutral"

    previous_spread = float(ema9.iloc[-2] - ema21.iloc[-2])
    current_spread = float(ema9.iloc[-1] - ema21.iloc[-1])
    choch = "bullish" if previous_spread <= 0 < current_spread else "bearish" if previous_spread >= 0 > current_spread else "neutral"

    timestamps = pd.to_datetime(frame.get("timestamps"), errors="coerce")
    latest_day = timestamps.dropna().dt.date.iloc[-1] if timestamps.notna().any() else None
    same_day = frame.loc[timestamps.dt.date == latest_day].copy() if latest_day else frame.tail(80).copy()
    same_ts = pd.to_datetime(same_day.get("timestamps"), errors="coerce")
    rth = same_day.loc[(same_ts.dt.hour * 60 + same_ts.dt.minute >= 570) & (same_ts.dt.hour * 60 + same_ts.dt.minute < 960)].copy()
    if rth.empty:
        rth = same_day
    typical = (rth["high"] + rth["low"] + rth["close"]) / 3.0
    cumulative_volume = rth["volume"].cumsum()
    vwap_value = float((typical * rth["volume"]).cumsum().iloc[-1] / cumulative_volume.iloc[-1]) if cumulative_volume.iloc[-1] > 0 else last
    vwap = "bullish" if last >= vwap_value else "bearish"

    fvg = "neutral"
    scan = frame.tail(15).reset_index(drop=True)
    for i in range(len(scan) - 1, 1, -1):
        if float(scan.loc[i, "low"]) > float(scan.loc[i - 2, "high"]):
            fvg = "bullish"
            break
        if float(scan.loc[i, "high"]) < float(scan.loc[i - 2, "low"]):
            fvg = "bearish"
            break

    orb = "neutral"
    if latest_day and not same_day.empty:
        minutes = same_ts.dt.hour * 60 + same_ts.dt.minute
        opening = same_day.loc[(minutes >= 570) & (minutes < 585)]
        if not opening.empty:
            orb_high = float(opening["high"].max())
            orb_low = float(opening["low"].min())
            orb = "bullish" if last > orb_high else "bearish" if last < orb_low else "neutral"
        else:
            orb_high = orb_low = None
    else:
        orb_high = orb_low = None

    recent = frame.tail(7).iloc[:-1]
    trigger = float(recent["high"].max()) if signal == "LONG" else float(recent["low"].min()) if signal == "SHORT" else last
    entry_low = trigger - atr * 0.10
    entry_high = trigger + atr * 0.10

    return {
        "symbol": symbol,
        "timeframe": "5m",
        "signal": signal,
        "price": last,
        "technical_score_preview": round(score, 1),
        "bos": bos,
        "choch": choch,
        "vwap": vwap,
        "fvg": fvg,
        "orb": orb,
        "volume": rvol >= 1.1,
        "rvol": round(rvol, 2),
        "atr": atr,
        "entry_low": entry_low,
        "entry_high": entry_high,
        "recent_high": float(frame.tail(20)["high"].max()),
        "recent_low": float(frame.tail(20)["low"].min()),
        "vwap_price": vwap_value,
        "orb_high": orb_high,
        "orb_low": orb_low,
    }


def _market_regime() -> dict[str, Any]:
    snapshots: list[dict[str, Any]] = []
    for symbol in ("SPY", "QQQ"):
        try:
            snapshots.append(_directional_features(symbol))
        except Exception:
            continue
    if not snapshots:
        return {
            "available": False,
            "status": "not_available",
            "reason": "SPY/QQQ 5-minute context is not available in the Kronos data folder yet.",
        }
    raw_scores = [float(item.get("technical_score_preview") or 50.0) for item in snapshots]
    raw = sum(raw_scores) / len(raw_scores)
    sentiment = "BULLISH" if raw >= 57 else "BEARISH" if raw <= 43 else "NEUTRAL"
    conviction = 50.0 + abs(raw - 50.0)
    return {
        "available": True,
        "status": "ok",
        "sentiment": sentiment,
        "score": round(min(100.0, conviction), 1),
        "raw_directional_score": round(raw, 1),
        "benchmarks": [
            {
                "symbol": item.get("symbol"),
                "signal": item.get("signal"),
                "score": item.get("technical_score_preview"),
                "vwap": item.get("vwap"),
            }
            for item in snapshots
        ],
        "beginner_explanation": (
            "The broader market is helping bullish trades."
            if sentiment == "BULLISH"
            else "The broader market is helping bearish trades."
            if sentiment == "BEARISH"
            else "The broader market is mixed, so individual trades need stronger proof."
        ),
    }


def _flow_context() -> dict[str, Any]:
    return {
        "available": False,
        "status": "not_configured",
        "reason": "Live options-flow scoring is not connected to the deployable MnT server yet.",
    }


def _decision_label(decision: Any) -> str:
    if isinstance(decision, dict):
        for key in ("decision", "action", "state", "status"):
            value = decision.get(key)
            if value:
                return str(value).upper()
    return str(decision).upper()


def _import_kronos_module(name: str):
    root = str(KRONOS_ROOT)
    if root not in sys.path:
        sys.path.insert(0, root)
    return importlib.import_module(name)


def _finalize_payload(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        payload["signal_id"] = record_signal(payload)
    except Exception as exc:
        payload["signal_id"] = None
        payload["signal_store_error"] = type(exc).__name__
    return payload


@router.post("/analyze/{symbol}")
async def analyze(symbol: str) -> dict[str, Any]:
    return await run_kronos_analysis(symbol)


@router.get("/gamma/{symbol}")
async def gamma(symbol: str, spot: float | None = Query(None, gt=0)) -> dict[str, Any]:
    symbol = symbol.strip().upper()
    if not SYMBOL_RE.fullmatch(symbol):
        raise HTTPException(status_code=400, detail="Invalid symbol")
    return await fetch_gamma_context(symbol, spot)


@router.get("/market-regime")
async def market_regime() -> dict[str, Any]:
    return _market_regime()


@router.get("/signals")
async def signals(symbol: str | None = Query(None), limit: int = Query(50, ge=1, le=500)) -> dict[str, Any]:
    if symbol is not None:
        symbol = symbol.strip().upper()
        if not SYMBOL_RE.fullmatch(symbol):
            raise HTTPException(status_code=400, detail="Invalid symbol")
    try:
        items = list_signals(symbol=symbol, limit=limit)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Signal history unavailable: {type(exc).__name__}") from exc
    return {"symbol": symbol, "count": len(items), "signals": items}


@router.post("/fusion/{symbol}")
async def fusion(
    symbol: str,
    max_contract_cost: float | None = Query(None, gt=0, le=100000),
) -> dict[str, Any]:
    symbol = symbol.strip().upper()
    kronos = await run_kronos_analysis(symbol)
    alert = _directional_features(symbol)
    market_gate = _opening_market_gate()
    gamma_context, market_context = await asyncio.gather(
        fetch_gamma_context(symbol, float(alert.get("price") or 0.0) or None),
        asyncio.to_thread(_market_regime),
    )
    flow_context = _flow_context()

    if market_gate["active"]:
        fusion_score = build_fusion_score(
            technical=alert,
            kronos=kronos,
            gamma=gamma_context,
            flow=flow_context,
            market=market_context,
            options=[],
        )
        return _finalize_payload({
            "symbol": symbol,
            "technical": _jsonable(alert),
            "kronos": _jsonable(kronos),
            "gamma": gamma_context,
            "flow": flow_context,
            "market_regime": market_context,
            "fusion_score": fusion_score,
            "decision": {
                "decision": "WATCH",
                "reason": market_gate["reason"],
            },
            "trade_plan": None,
            "options": [],
            "option_scan_ran": False,
            "market_gate": market_gate,
            "research_only": True,
            "note": "Opening lockout active. No actionable setup is produced until the first 5-minute candle closes at 09:35 ET.",
        })

    if alert["signal"] == "NEUTRAL":
        fusion_score = build_fusion_score(
            technical=alert,
            kronos=kronos,
            gamma=gamma_context,
            flow=flow_context,
            market=market_context,
            options=[],
        )
        return _finalize_payload({
            "symbol": symbol,
            "technical": alert,
            "kronos": kronos,
            "gamma": gamma_context,
            "flow": flow_context,
            "market_regime": market_context,
            "fusion_score": fusion_score,
            "decision": {"decision": "WATCH", "reason": "Dashboard technical layer is neutral."},
            "trade_plan": None,
            "options": [],
            "option_scan_ran": False,
            "market_gate": market_gate,
            "research_only": True,
        })

    try:
        decision_engine = _import_kronos_module("trading.decision_engine")
        trade_plan_module = _import_kronos_module("trading.trade_plan")
        decision = decision_engine.evaluate_decision(alert, kronos)
        trade_plan = trade_plan_module.build_trade_plan(alert, kronos=kronos, decision=decision)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Decision bridge failed: {type(exc).__name__}: {exc}") from exc

    options: list[Any] = []
    option_scan_ran = False
    label = _decision_label(decision)
    if "CONFIRM" in label and "REJECT" not in label:
        try:
            selector = _import_kronos_module("trading.options_selector")
            direction = alert["signal"]
            expected_move = float(kronos.get("median_2h_move_pct") or kronos.get("median_1h_move_pct") or 0.0)
            agreement = int(kronos.get("bullish_paths") or 0) if direction == "LONG" else int(kronos.get("bearish_paths") or 0)
            options = selector.select_options(
                symbol=symbol,
                direction=direction,
                expected_move_pct=expected_move,
                stability=str(kronos.get("stability") or "LOW"),
                agreement=agreement,
                style="auto",
                max_contract_cost=max_contract_cost,
                limit=3,
            )
            option_scan_ran = True
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Option selector failed: {type(exc).__name__}: {exc}") from exc

    json_options = _jsonable(options)
    fusion_score = build_fusion_score(
        technical=_jsonable(alert),
        kronos=_jsonable(kronos),
        gamma=gamma_context,
        flow=flow_context,
        market=market_context,
        options=json_options,
    )
    return _finalize_payload({
        "symbol": symbol,
        "technical": _jsonable(alert),
        "kronos": _jsonable(kronos),
        "gamma": gamma_context,
        "flow": flow_context,
        "market_regime": market_context,
        "fusion_score": fusion_score,
        "decision": _jsonable(decision),
        "trade_plan": _jsonable(trade_plan),
        "options": json_options,
        "option_scan_ran": option_scan_ran,
        "market_gate": market_gate,
        "research_only": True,
        "note": "Option candidates are mechanical model fits. No order is placed by this dashboard.",
    })
