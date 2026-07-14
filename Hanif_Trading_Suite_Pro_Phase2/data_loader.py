from __future__ import annotations
from pathlib import Path
import pandas as pd

REQUIRED = {"Open","High","Low","Close","Volume"}

def _normalize(df: pd.DataFrame) -> pd.DataFrame:
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df.rename(columns={c: c.title() for c in df.columns})
    missing = REQUIRED - set(df.columns)
    if missing:
        raise ValueError(f"Missing required columns: {sorted(missing)}")
    df = df[["Open","High","Low","Close","Volume"]].dropna().sort_index()
    if not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index)
    if df.index.tz is not None:
        df.index = df.index.tz_convert("America/New_York").tz_localize(None)
    return df

def load_yfinance(symbol: str, period: str, interval: str) -> pd.DataFrame:
    import yfinance as yf
    df = yf.download(symbol, period=period, interval=interval, auto_adjust=False,
                     progress=False, prepost=False, threads=True)
    if df.empty:
        raise RuntimeError("No data returned. Try a shorter period or different interval.")
    return _normalize(df)

def load_csv(path: str | Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    date_cols = [c for c in df.columns if c.lower() in {"date","datetime","timestamp","time"}]
    if not date_cols:
        raise ValueError("CSV requires Date/Datetime/Timestamp/Time column.")
    dc = date_cols[0]
    df[dc] = pd.to_datetime(df[dc])
    return _normalize(df.set_index(dc))
