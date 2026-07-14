from __future__ import annotations
import numpy as np
import pandas as pd

def ema(series: pd.Series, length: int) -> pd.Series:
    return series.ewm(span=length, adjust=False).mean()

def rsi(close: pd.Series, length: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1/length, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1/length, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    return (100 - (100/(1+rs))).fillna(50)

def true_range(df: pd.DataFrame) -> pd.Series:
    prev = df["Close"].shift(1)
    return pd.concat([
        df["High"] - df["Low"],
        (df["High"] - prev).abs(),
        (df["Low"] - prev).abs()
    ], axis=1).max(axis=1)

def atr(df: pd.DataFrame, length: int = 14) -> pd.Series:
    return true_range(df).ewm(alpha=1/length, adjust=False).mean()

def adx(df: pd.DataFrame, length: int = 14):
    up = df["High"].diff()
    down = -df["Low"].diff()
    plus_dm = pd.Series(np.where((up > down) & (up > 0), up, 0.0), index=df.index)
    minus_dm = pd.Series(np.where((down > up) & (down > 0), down, 0.0), index=df.index)
    tr = true_range(df).ewm(alpha=1/length, adjust=False).mean()
    plus_di = 100 * plus_dm.ewm(alpha=1/length, adjust=False).mean() / tr
    minus_di = 100 * minus_dm.ewm(alpha=1/length, adjust=False).mean() / tr
    dx = 100 * (plus_di-minus_di).abs() / (plus_di+minus_di).replace(0,np.nan)
    adx_value = dx.ewm(alpha=1/length, adjust=False).mean().fillna(0)
    return plus_di.fillna(0), minus_di.fillna(0), adx_value

def session_vwap(df: pd.DataFrame) -> pd.Series:
    typical = (df["High"]+df["Low"]+df["Close"])/3
    session = pd.Series(df.index.date, index=df.index)
    pv = (typical*df["Volume"]).groupby(session).cumsum()
    vol = df["Volume"].groupby(session).cumsum()
    return pv / vol.replace(0,np.nan)
