from __future__ import annotations

from opportunity_service import build_position_profile, rank_opportunities


def _trend_bars(start: float, step: float, count: int = 260):
    rows = []
    price = start
    for index in range(count):
        price += step
        rows.append(
            {
                "open": price - step * 0.25,
                "high": price * 1.003,
                "low": price * 0.997,
                "close": price,
                "volume": 1_000_000 + index * 100,
            }
        )
    return rows


def test_strong_daily_trend_builds_swing_and_hold_profile() -> None:
    profile = build_position_profile("nvda", _trend_bars(100.0, 0.25), intraday_score=88.0)
    assert profile is not None
    assert profile["symbol"] == "NVDA"
    assert profile["score_source"] == "mnt_engine.score_position_bars"
    assert profile["swing_score"] >= 66
    assert profile["swing_eligible"] is True
    assert profile["hold_eligible"] is True
    assert profile["best_fit"] in {"3-4_MONTH_SHARES", "SWING_SHARES_OR_30_60D_OPTION_WATCH"}
    assert profile["research_only"] is True


def test_insufficient_daily_history_returns_none() -> None:
    assert build_position_profile("SPY", _trend_bars(100.0, 0.1, count=40), intraday_score=80) is None


def test_intraday_score_blends_into_swing_score_without_replacing_position_score() -> None:
    low_fast = build_position_profile("AAPL", _trend_bars(100.0, 0.18), intraday_score=45.0)
    high_fast = build_position_profile("AAPL", _trend_bars(100.0, 0.18), intraday_score=90.0)
    assert low_fast is not None and high_fast is not None
    assert low_fast["score"] == high_fast["score"]
    assert high_fast["swing_score"] > low_fast["swing_score"]


def test_rank_opportunities_uses_lane_specific_scores() -> None:
    rows = [
        {"symbol": "AAA", "score": 80, "swing_score": 72, "swing_eligible": True, "hold_eligible": True},
        {"symbol": "BBB", "score": 75, "swing_score": 90, "swing_eligible": True, "hold_eligible": True},
        {"symbol": "CCC", "score": 95, "swing_score": 60, "swing_eligible": False, "hold_eligible": True},
    ]
    swing = rank_opportunities(rows, lane="swing", limit=2)
    hold = rank_opportunities(rows, lane="hold", limit=2)
    assert [row["symbol"] for row in swing] == ["BBB", "AAA"]
    assert [row["symbol"] for row in hold] == ["CCC", "AAA"]
