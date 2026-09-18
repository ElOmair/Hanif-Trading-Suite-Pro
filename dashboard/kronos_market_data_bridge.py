from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd
from dotenv import load_dotenv

DASHBOARD_ROOT = Path(__file__).resolve().parent
KRONOS_ROOT = Path(os.getenv("KRONOS_ROOT", "/home/airomair/Kronos")).expanduser()
DATA_DIR = KRONOS_ROOT / "trading" / "data"

# The dashboard service already supplies these variables through systemd. These
# file loads make the bridge work when it is run directly from a shell too.
load_dotenv(KRONOS_ROOT / ".env")
load_dotenv(DASHBOARD_ROOT / ".env")
load_dotenv(DASHBOARD_ROOT / "mnt.env", override=True)


def _normalize_schwab_rows(rows: list[dict[str, Any]]) -> pd.DataFrame:
    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame
    required = {"time", "open", "high", "low", "close", "volume"}
    missing = required.difference(frame.columns)
    if missing:
        raise RuntimeError(f"Schwab rows are missing required fields: {sorted(missing)}")
    timestamps = pd.to_datetime(frame["time"], unit="s", utc=True)
    frame["timestamps"] = timestamps.dt.tz_convert("America/New_York").dt.tz_localize(None)
    return frame[["timestamps", "open", "high", "low", "close", "volume"]].tail(400).copy()


def _alpaca_rows(symbol: str) -> pd.DataFrame:
    from alpaca.data.enums import DataFeed
    from alpaca.data.historical.stock import StockHistoricalDataClient
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

    api_key = os.getenv("ALPACA_API_KEY", "").strip()
    secret_key = os.getenv("ALPACA_SECRET_KEY", "").strip()
    if not api_key or not secret_key:
        raise RuntimeError("Alpaca fallback credentials are not configured")

    client = StockHistoricalDataClient(api_key, secret_key)
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=14)
    request = StockBarsRequest(
        symbol_or_symbols=[symbol],
        timeframe=TimeFrame(5, TimeFrameUnit.Minute),
        start=start,
        end=end,
        limit=1000,
        feed=DataFeed.IEX,
    )
    bars = client.get_stock_bars(request)
    frame = bars.df
    if frame.empty:
        raise RuntimeError(f"No Alpaca fallback market data returned for {symbol}")
    if isinstance(frame.index, pd.MultiIndex):
        frame = frame.xs(symbol, level="symbol")
    frame = frame.reset_index().tail(400).copy()
    frame["timestamps"] = (
        pd.to_datetime(frame["timestamp"], utc=True)
        .dt.tz_convert("America/New_York")
        .dt.tz_localize(None)
    )
    return frame[["timestamps", "open", "high", "low", "close", "volume"]].copy()


async def _fetch_rows(symbol: str) -> tuple[pd.DataFrame, str, str | None]:
    schwab_error: str | None = None
    try:
        from schwab_market_data import bars as schwab_bars
        from schwab_market_data import market_data_ready

        if market_data_ready():
            payload = await schwab_bars(symbol, "5m", 400)
            rows = payload.get("bars") if isinstance(payload, dict) else None
            if isinstance(rows, list) and len(rows) >= 30:
                return _normalize_schwab_rows(rows), "schwab", None
            schwab_error = "insufficient_schwab_bars"
        else:
            schwab_error = "schwab_not_ready"
    except Exception as exc:
        schwab_error = f"{type(exc).__name__}: {exc}"

    frame = await asyncio.to_thread(_alpaca_rows, symbol)
    return frame, "alpaca_iex", schwab_error


def _write_output(symbol: str, frame: pd.DataFrame, provider: str, schwab_error: str | None) -> Path:
    if len(frame) < 30:
        raise RuntimeError(f"Not enough 5-minute market data returned for {symbol}: {len(frame)} rows")

    out = frame.tail(400).copy()
    for column in ("open", "high", "low", "close", "volume"):
        out[column] = pd.to_numeric(out[column], errors="coerce")
    out = out.dropna(subset=["timestamps", "open", "high", "low", "close", "volume"])
    if len(out) < 30:
        raise RuntimeError(f"Not enough valid 5-minute rows remained for {symbol}: {len(out)}")

    out["amount"] = out["volume"] * ((out["open"] + out["high"] + out["low"] + out["close"]) / 4.0)
    out = out[["timestamps", "open", "high", "low", "close", "volume", "amount"]]

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    output_path = DATA_DIR / f"{symbol}_5m.csv"
    temp_path = output_path.with_suffix(".csv.tmp")
    out.to_csv(temp_path, index=False)
    temp_path.replace(output_path)

    metadata = {
        "symbol": symbol,
        "timeframe": "5m",
        "provider": provider,
        "fallback_used": provider != "schwab",
        "schwab_error": schwab_error,
        "bars": len(out),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "output": str(output_path),
    }
    metadata_path = DATA_DIR / f"{symbol}_5m.source.json"
    metadata_temp = metadata_path.with_suffix(".json.tmp")
    metadata_temp.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    metadata_temp.replace(metadata_path)
    return output_path


async def refresh_symbol(symbol: str) -> dict[str, Any]:
    symbol = symbol.strip().upper()
    if not symbol or not all(character.isalnum() or character in ".-" for character in symbol):
        raise RuntimeError("Invalid symbol")
    frame, provider, schwab_error = await _fetch_rows(symbol)
    output_path = _write_output(symbol, frame, provider, schwab_error)
    return {
        "symbol": symbol,
        "provider": provider,
        "fallback_used": provider != "schwab",
        "schwab_error": schwab_error,
        "bars": min(len(frame), 400),
        "output": str(output_path),
    }


async def _main() -> int:
    symbol = sys.argv[1].strip().upper() if len(sys.argv) > 1 else "NVDA"
    result = await refresh_symbol(symbol)
    print()
    print(f"Symbol: {result['symbol']}")
    print(f"Market data provider: {result['provider']}")
    print(f"Fallback used: {result['fallback_used']}")
    if result.get("schwab_error"):
        print(f"Schwab status: {result['schwab_error']}")
    print(f"Bars returned: {result['bars']}")
    print(f"Saved: {result['output']}")
    print()
    frame = pd.read_csv(result["output"])
    print(frame.tail(5).to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
