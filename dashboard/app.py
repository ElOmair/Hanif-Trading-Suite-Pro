from __future__ import annotations

import asyncio
import os
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx
import pandas as pd
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from alpaca.data.enums import DataFeed
from alpaca.data.historical.stock import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest, StockLatestBarRequest, StockLatestQuoteRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

from kronos_api import router as kronos_router

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT.parent / ".env")
load_dotenv(ROOT / ".env")

SYMBOL_RE = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")
DEFAULT_UNIVERSE = (
    "SPY,QQQ,IWM,DIA,NVDA,AMD,AAPL,MSFT,AMZN,META,GOOGL,TSLA,AVGO,"
    "PLTR,SOFI,SMCI,COIN,MARA,GME,CRSR,NVTS,UBER,NFLX,CRM,ORCL,MU,"
    "ARM,INTC,QCOM,MRVL,JPM,BAC,GS,XOM,CVX,LLY,UNH,WMT,COST"
)


def _feed() -> DataFeed:
    return DataFeed.SIP if os.getenv("ALPACA_DATA_FEED", "iex").strip().lower() == "sip" else DataFeed.IEX


API_KEY = os.getenv("ALPACA_API_KEY", "").strip()
API_SECRET = os.getenv("ALPACA_SECRET_KEY", "").strip()
KRONOS_API_URL = os.getenv("KRONOS_API_URL", "http://127.0.0.1:8000").rstrip("/")
RADAR_UNIVERSE = [s.strip().upper() for s in os.getenv("RADAR_UNIVERSE", DEFAULT_UNIVERSE).split(",") if s.strip()]

alpaca: StockHistoricalDataClient | None = None
if API_KEY and API_SECRET:
    alpaca = StockHistoricalDataClient(API_KEY, API_SECRET)

app = FastAPI(title="Hanif Trading Suite Dashboard", version="0.1.0")
app.include_router(kronos_router)
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
_radar_cache: dict[str, Any] = {"expires": 0.0, "data": None}


def require_alpaca() -> StockHistoricalDataClient:
    if alpaca is None:
        raise HTTPException(status_code=503, detail="Alpaca credentials are not configured on the dashboard server.")
    return alpaca


def normalize_symbol(symbol: str) -> str:
    symbol = symbol.strip().upper()
    if not SYMBOL_RE.match(symbol):
        raise HTTPException(status_code=400, detail="Invalid symbol")
    return symbol


def timeframe_from_text(value: str) -> TimeFrame:
    mapping = {
        "1m": TimeFrame.Minute,
        "5m": TimeFrame(5, TimeFrameUnit.Minute),
        "15m": TimeFrame(15, TimeFrameUnit.Minute),
        "30m": TimeFrame(30, TimeFrameUnit.Minute),
        "1h": TimeFrame.Hour,
        "1d": TimeFrame.Day,
    }
    key = value.strip().lower()
    if key not in mapping:
        raise HTTPException(status_code=400, detail="Unsupported timeframe")
    return mapping[key]


def start_for_timeframe(timeframe: str, limit: int) -> datetime:
    now = datetime.now(timezone.utc)
    key = timeframe.lower()
    if key in {"1m", "5m", "15m", "30m"}:
        return now - timedelta(days=max(7, min(45, (limit // 75) + 7)))
    if key == "1h":
        return now - timedelta(days=max(30, min(180, limit // 6 + 14)))
    return now - timedelta(days=max(400, limit * 2))


def bars_to_rows(df: pd.DataFrame, symbol: str, limit: int) -> list[dict[str, Any]]:
    if df is None or df.empty:
        return []
    frame = df.reset_index()
    if "symbol" in frame.columns:
        frame = frame[frame["symbol"] == symbol]
    frame = frame.sort_values("timestamp").tail(limit)
    rows = []
    for row in frame.itertuples(index=False):
        ts = pd.Timestamp(getattr(row, "timestamp"))
        if ts.tzinfo is None:
            ts = ts.tz_localize("UTC")
        rows.append({
            "time": int(ts.timestamp()),
            "open": float(getattr(row, "open")),
            "high": float(getattr(row, "high")),
            "low": float(getattr(row, "low")),
            "close": float(getattr(row, "close")),
            "volume": float(getattr(row, "volume")),
        })
    return rows


def _technical_snapshot(frame: pd.DataFrame, symbol: str) -> dict[str, Any] | None:
    if frame is None or frame.empty:
        return None
    frame = frame.sort_values("timestamp").copy().tail(120)
    if len(frame) < 25:
        return None

    close = frame["close"].astype(float)
    high = frame["high"].astype(float)
    low = frame["low"].astype(float)
    volume = frame["volume"].astype(float)
    ema9 = close.ewm(span=9, adjust=False).mean()
    ema21 = close.ewm(span=21, adjust=False).mean()
    prev_close = close.shift(1)
    true_range = pd.concat([(high - low), (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
    atr = true_range.rolling(14).mean()
    avg_vol = volume.shift(1).rolling(20).mean()

    last = float(close.iloc[-1])
    momentum_30m = float((last / close.iloc[-7] - 1.0) * 100.0) if len(close) >= 7 else 0.0
    rvol = float(volume.iloc[-1] / avg_vol.iloc[-1]) if pd.notna(avg_vol.iloc[-1]) and avg_vol.iloc[-1] > 0 else 1.0
    atr_pct = float(atr.iloc[-1] / last * 100.0) if pd.notna(atr.iloc[-1]) and last > 0 else 0.0
    ema_spread_pct = float((ema9.iloc[-1] / ema21.iloc[-1] - 1.0) * 100.0) if ema21.iloc[-1] else 0.0

    score = 50.0
    score += max(-18.0, min(18.0, ema_spread_pct * 45.0))
    score += max(-18.0, min(18.0, momentum_30m * 9.0))
    if rvol >= 1.5:
        score += 8.0 if momentum_30m >= 0 else -8.0
    elif rvol >= 1.1:
        score += 4.0 if momentum_30m >= 0 else -4.0
    score = max(0.0, min(100.0, score))

    direction = "LONG" if score >= 62 else "SHORT" if score <= 38 else "NEUTRAL"
    rank_score = score if direction == "LONG" else (100.0 - score if direction == "SHORT" else 0.0)
    return {
        "symbol": symbol,
        "price": round(last, 4),
        "direction": direction,
        "score": round(score, 1),
        "rank_score": round(rank_score, 1),
        "momentum_30m_pct": round(momentum_30m, 2),
        "rvol": round(rvol, 2),
        "atr_pct": round(atr_pct, 2),
        "ema9": round(float(ema9.iloc[-1]), 4),
        "ema21": round(float(ema21.iloc[-1]), 4),
    }


@app.get("/")
def index() -> FileResponse:
    return FileResponse(ROOT / "static" / "index.html")


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "service": "hanif-trading-dashboard",
        "version": "0.1.0",
        "alpaca_configured": alpaca is not None,
        "feed": os.getenv("ALPACA_DATA_FEED", "iex").lower(),
    }


@app.get("/api/system")
async def system_status() -> dict[str, Any]:
    kronos: dict[str, Any] = {"online": False}
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            response = await client.get(f"{KRONOS_API_URL}/health")
            kronos = {"online": True, "health": response.json()} if response.is_success else {"online": False, "status_code": response.status_code}
    except Exception as exc:
        kronos = {"online": False, "error": type(exc).__name__}
    return {"kronos": kronos, "alpaca": {"configured": alpaca is not None, "feed": _feed().value}}


@app.get("/api/bars/{symbol}")
async def bars(symbol: str, timeframe: str = Query("5m"), limit: int = Query(400, ge=50, le=1000)) -> dict[str, Any]:
    symbol = normalize_symbol(symbol)
    client = require_alpaca()
    request = StockBarsRequest(
        symbol_or_symbols=symbol,
        timeframe=timeframe_from_text(timeframe),
        start=start_for_timeframe(timeframe, limit),
        feed=_feed(),
    )
    barset = await asyncio.to_thread(client.get_stock_bars, request)
    return {"symbol": symbol, "timeframe": timeframe.lower(), "bars": bars_to_rows(barset.df, symbol, limit)}


@app.get("/api/tick/{symbol}")
async def tick(symbol: str) -> dict[str, Any]:
    symbol = normalize_symbol(symbol)
    client = require_alpaca()
    quote_req = StockLatestQuoteRequest(symbol_or_symbols=symbol, feed=_feed())
    bar_req = StockLatestBarRequest(symbol_or_symbols=symbol, feed=_feed())
    quote_map, bar_map = await asyncio.gather(
        asyncio.to_thread(client.get_stock_latest_quote, quote_req),
        asyncio.to_thread(client.get_stock_latest_bar, bar_req),
    )
    quote = quote_map.get(symbol)
    bar = bar_map.get(symbol)
    payload: dict[str, Any] = {"symbol": symbol}
    if quote is not None:
        payload["quote"] = {
            "bid": float(quote.bid_price or 0), "ask": float(quote.ask_price or 0),
            "bid_size": float(quote.bid_size or 0), "ask_size": float(quote.ask_size or 0),
            "timestamp": quote.timestamp.isoformat() if quote.timestamp else None,
        }
    if bar is not None:
        ts = pd.Timestamp(bar.timestamp)
        if ts.tzinfo is None:
            ts = ts.tz_localize("UTC")
        payload["bar"] = {
            "time": int(ts.timestamp()), "open": float(bar.open), "high": float(bar.high),
            "low": float(bar.low), "close": float(bar.close), "volume": float(bar.volume),
        }
    return payload


@app.get("/api/radar")
async def radar(limit: int = Query(8, ge=3, le=20)) -> dict[str, Any]:
    now = time.monotonic()
    if _radar_cache["data"] is not None and now < _radar_cache["expires"]:
        cached = dict(_radar_cache["data"])
        cached["cached"] = True
        cached["longs"] = cached["longs"][:limit]
        cached["shorts"] = cached["shorts"][:limit]
        return cached

    client = require_alpaca()
    request = StockBarsRequest(
        symbol_or_symbols=RADAR_UNIVERSE,
        timeframe=TimeFrame(5, TimeFrameUnit.Minute),
        start=datetime.now(timezone.utc) - timedelta(days=7),
        feed=_feed(),
    )
    barset = await asyncio.to_thread(client.get_stock_bars, request)
    df = barset.df.reset_index() if not barset.df.empty else pd.DataFrame()
    snapshots = []
    if not df.empty and "symbol" in df.columns:
        for symbol_name, frame in df.groupby("symbol", sort=False):
            snapshot = _technical_snapshot(frame, str(symbol_name))
            if snapshot:
                snapshots.append(snapshot)

    longs = sorted((s for s in snapshots if s["direction"] == "LONG"), key=lambda x: x["rank_score"], reverse=True)
    shorts = sorted((s for s in snapshots if s["direction"] == "SHORT"), key=lambda x: x["rank_score"], reverse=True)
    data = {
        "generated_at": datetime.now(timezone.utc).isoformat(), "feed": _feed().value,
        "universe_size": len(RADAR_UNIVERSE), "longs": longs, "shorts": shorts,
        "cached": False, "note": "Radar score is a fast technical pre-filter, not a trade recommendation.",
    }
    _radar_cache["data"] = data
    _radar_cache["expires"] = now + 60.0
    result = dict(data)
    result["longs"] = longs[:limit]
    result["shorts"] = shorts[:limit]
    return result


@app.websocket("/ws/market/{symbol}")
async def market_socket(websocket: WebSocket, symbol: str) -> None:
    try:
        symbol = normalize_symbol(symbol)
    except HTTPException:
        await websocket.close(code=1008)
        return
    if alpaca is None:
        await websocket.close(code=1011)
        return

    await websocket.accept()
    client = require_alpaca()
    try:
        while True:
            quote_req = StockLatestQuoteRequest(symbol_or_symbols=symbol, feed=_feed())
            bar_req = StockLatestBarRequest(symbol_or_symbols=symbol, feed=_feed())
            quote_map, bar_map = await asyncio.gather(
                asyncio.to_thread(client.get_stock_latest_quote, quote_req),
                asyncio.to_thread(client.get_stock_latest_bar, bar_req),
            )
            quote = quote_map.get(symbol)
            bar = bar_map.get(symbol)
            message: dict[str, Any] = {"type": "market", "symbol": symbol}
            if quote is not None:
                bid, ask = float(quote.bid_price or 0), float(quote.ask_price or 0)
                mid = (bid + ask) / 2.0 if bid and ask else (ask or bid)
                message["quote"] = {"bid": bid, "ask": ask, "mid": round(mid, 4) if mid else 0, "timestamp": quote.timestamp.isoformat() if quote.timestamp else None}
            if bar is not None:
                ts = pd.Timestamp(bar.timestamp)
                if ts.tzinfo is None:
                    ts = ts.tz_localize("UTC")
                message["bar"] = {
                    "time": int(ts.timestamp()), "open": float(bar.open), "high": float(bar.high),
                    "low": float(bar.low), "close": float(bar.close), "volume": float(bar.volume),
                }
            await websocket.send_json(message)
            await asyncio.sleep(1.0)
    except WebSocketDisconnect:
        return
    except Exception:
        try:
            await websocket.close(code=1011)
        except Exception:
            pass
