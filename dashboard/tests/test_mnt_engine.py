from __future__ import annotations

from mnt_engine import build_fusion_score, score_gamma, score_position_bars, score_technical


def aligned_technical() -> dict:
    return {
        "signal": "LONG",
        "price": 100.0,
        "technical_score_preview": 84.0,
        "bos": "bullish",
        "choch": "bullish",
        "vwap": "bullish",
        "fvg": "bullish",
        "orb": "neutral",
        "volume": True,
        "rvol": 1.8,
    }


def aligned_kronos() -> dict:
    return {
        "final_bias": "BULLISH",
        "bias_agreement_pct": 78.0,
        "stability": "HIGH",
    }


def test_missing_layers_are_reweighted_not_scored_as_zero() -> None:
    result = build_fusion_score(technical=aligned_technical(), kronos=aligned_kronos())
    assert result["score"] > 70
    assert 0 < result["coverage_pct"] < 100
    assert "gamma" in result["missing_layers"]
    assert "flow" in result["missing_layers"]
    assert result["components"]["gamma"] is None


def test_gamma_alignment_improves_long_setup() -> None:
    expansion = score_gamma(
        {
            "available": True,
            "regime": "NEGATIVE_GAMMA_EXPANSION",
            "gamma_flip": 99.0,
            "call_wall": 103.0,
            "put_wall": 96.0,
        },
        "LONG",
        100.0,
    )
    pinning = score_gamma(
        {
            "available": True,
            "regime": "POSITIVE_GAMMA_PIN",
            "gamma_flip": 101.0,
            "call_wall": 100.2,
            "put_wall": 96.0,
        },
        "LONG",
        100.0,
    )
    assert expansion is not None and pinning is not None
    assert expansion["score"] > pinning["score"]


def test_short_technical_score_is_directionally_inverted() -> None:
    result = score_technical(
        {
            "signal": "SHORT",
            "technical_score_preview": 18.0,
            "bos": "bearish",
            "choch": "bearish",
            "vwap": "bearish",
            "fvg": "neutral",
            "orb": "bearish",
        }
    )
    assert result is not None
    assert result["score"] > 80


def test_position_bar_score_returns_position_fields() -> None:
    bars = []
    price = 70.0
    for index in range(260):
        price *= 1.0015
        bars.append({"close": price, "high": price * 1.01, "low": price * 0.99})
    result = score_position_bars(bars)
    assert result is not None
    assert result["score"] >= 70
    assert result["trend"] in {"UPTREND", "IMPROVING"}
    assert result["watch_low"] < result["watch_high"]
