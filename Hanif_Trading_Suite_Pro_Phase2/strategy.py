from __future__ import annotations
import pandas as pd
from indicators import adx, atr, ema, rsi, session_vwap

def prepare_signals(df: pd.DataFrame, c: dict) -> pd.DataFrame:
    out = df.copy()
    out["EMA_FAST"] = ema(out["Close"], int(c["ema_fast"]))
    out["EMA_SLOW"] = ema(out["Close"], int(c["ema_slow"]))
    out["EMA_TREND"] = ema(out["Close"], int(c["ema_trend"]))
    out["RSI"] = rsi(out["Close"], int(c["rsi_length"]))
    out["ATR"] = atr(out, int(c["atr_length"]))
    out["PLUS_DI"], out["MINUS_DI"], out["ADX"] = adx(out, int(c["adx_length"]))
    out["VWAP"] = session_vwap(out)
    out["AVG_VOLUME"] = out["Volume"].rolling(int(c["volume_length"])).mean()
    out["RVOL"] = out["Volume"] / out["AVG_VOLUME"].replace(0, pd.NA)
    out["BODY_ATR"] = (out["Close"] - out["Open"]).abs() / out["ATR"].replace(0, pd.NA)
    out["VWAP_DIST_ATR"] = (out["Close"] - out["VWAP"]).abs() / out["ATR"].replace(0, pd.NA)

    out["PRIOR_HIGH"] = out["High"].shift(1).rolling(10).max()
    out["PRIOR_LOW"] = out["Low"].shift(1).rolling(10).min()
    out["BULL_BREAKOUT"] = (out["Close"] > out["PRIOR_HIGH"]) & (out["Close"] > out["Open"])
    out["BEAR_BREAKOUT"] = (out["Close"] < out["PRIOR_LOW"]) & (out["Close"] < out["Open"])
    out["BULL_PULLBACK"] = (out["Low"] <= out["EMA_FAST"]) & (out["Close"] > out["EMA_FAST"]) & (out["Close"] > out["Open"])
    out["BEAR_PULLBACK"] = (out["High"] >= out["EMA_FAST"]) & (out["Close"] < out["EMA_FAST"]) & (out["Close"] < out["Open"])

    out["LONG_SETUP_TYPE"] = "NONE"
    out.loc[out["BULL_PULLBACK"], "LONG_SETUP_TYPE"] = "PULLBACK"
    out.loc[out["BULL_BREAKOUT"], "LONG_SETUP_TYPE"] = "BREAKOUT"
    out["SHORT_SETUP_TYPE"] = "NONE"
    out.loc[out["BEAR_PULLBACK"], "SHORT_SETUP_TYPE"] = "PULLBACK"
    out.loc[out["BEAR_BREAKOUT"], "SHORT_SETUP_TYPE"] = "BREAKOUT"

    out["BULL_SCORE"] = (
        (out["Close"] > out["EMA_TREND"]).astype(int) * 20 +
        (out["EMA_FAST"] > out["EMA_SLOW"]).astype(int) * 20 +
        (out["Close"] > out["VWAP"]).astype(int) * 15 +
        (out["RSI"] >= 55).astype(int) * 10 +
        (out["PLUS_DI"] > out["MINUS_DI"]).astype(int) * 10 +
        (out["ADX"] >= float(c["minimum_adx"])).astype(int) * 10 +
        (out["RVOL"] >= float(c["minimum_rvol"])).astype(int) * 15
    )
    out["BEAR_SCORE"] = (
        (out["Close"] < out["EMA_TREND"]).astype(int) * 20 +
        (out["EMA_FAST"] < out["EMA_SLOW"]).astype(int) * 20 +
        (out["Close"] < out["VWAP"]).astype(int) * 15 +
        (out["RSI"] <= 45).astype(int) * 10 +
        (out["MINUS_DI"] > out["PLUS_DI"]).astype(int) * 10 +
        (out["ADX"] >= float(c["minimum_adx"])).astype(int) * 10 +
        (out["RVOL"] >= float(c["minimum_rvol"])).astype(int) * 15
    )

    t = out.index.strftime("%H:%M")
    session_ok = (t >= c["session_start"]) & (t <= c["session_end"])
    body_ok = out["BODY_ATR"] >= float(c["minimum_body_atr"])
    distance_ok = out["VWAP_DIST_ATR"] <= float(c["maximum_vwap_distance_atr"])

    out["LONG_SIGNAL"] = (
        bool(c.get("allow_long", True)) &
        (out["BULL_SCORE"] >= int(c["minimum_score"])) &
        (out["BULL_PULLBACK"] | out["BULL_BREAKOUT"]) &
        session_ok & body_ok & distance_ok
    )
    out["SHORT_SIGNAL"] = (
        bool(c.get("allow_short", True)) &
        (out["BEAR_SCORE"] >= int(c["minimum_score"])) &
        (out["BEAR_PULLBACK"] | out["BEAR_BREAKOUT"]) &
        session_ok & body_ok & distance_ok
    )
    return out
