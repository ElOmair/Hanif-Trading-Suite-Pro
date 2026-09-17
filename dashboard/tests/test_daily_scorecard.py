from datetime import datetime, timezone

import daily_scorecard


def _trade(trade_id, symbol, direction="LONG", delivered=True, signal_id=None):
    return {
        "id": trade_id,
        "signal_id": signal_id or trade_id,
        "created_at": "2026-09-17T14:00:00+00:00",
        "symbol": symbol,
        "direction": direction,
        "fusion_score": 80,
        "coverage_pct": 75,
        "option_symbol": f"{symbol}261016C00100000",
        "discord_sent": 1 if delivered else 0,
    }


def _mark(mark_id, trade_id, value, lag=2):
    return {
        "id": mark_id,
        "shadow_trade_id": trade_id,
        "option_symbol": f"OPT{trade_id}",
        "horizon_minutes": 60,
        "lag_minutes": lag,
        "return_bid_vs_entry_ask_pct": value,
    }


def test_daily_scorecard_summarizes_option_and_underlying_results(monkeypatch):
    labels = {1: "WIN", 2: "WIN", 3: "LOSS", 4: "WIN"}
    monkeypatch.setattr(
        daily_scorecard,
        "get_signal",
        lambda signal_id: {"outcome": {"calibration_label": labels[int(signal_id)]}},
    )
    trades = [
        _trade(1, "SPY"),
        _trade(2, "QQQ"),
        _trade(3, "TSLA", direction="SHORT"),
        _trade(4, "NVDA", delivered=False),
    ]
    marks = [_mark(1, 1, 30), _mark(2, 2, 10), _mark(3, 3, -12), _mark(4, 4, 55)]
    report = daily_scorecard.build_daily_scorecard(
        "2026-09-17",
        now=datetime(2026, 9, 17, 20, 0, tzinfo=timezone.utc),
        trades=trades,
        marks=marks,
    )
    assert report["ready_ideas"] == 4
    assert report["discord_delivered"] == 3
    assert report["long_ideas"] == 3
    assert report["short_ideas"] == 1
    assert report["underlying_outcomes"]["target_first_win_rate_pct"] == 75.0
    assert report["option_marks"]["count"] == 4
    assert report["option_marks"]["average_return_pct"] == 20.75
    assert report["option_marks"]["positive_rate_pct"] == 75.0
    assert report["quality_state"] == "STRONG"
    assert report["best_option"]["underlying"] == "NVDA"
    assert report["worst_option"]["underlying"] == "TSLA"


def test_daily_scorecard_ignores_wrong_day_horizon_and_late_marks(monkeypatch):
    monkeypatch.setattr(daily_scorecard, "get_signal", lambda signal_id: None)
    trades = [
        _trade(1, "SPY"),
        {**_trade(2, "QQQ"), "created_at": "2026-09-16T14:00:00+00:00"},
    ]
    marks = [
        _mark(1, 1, 20),
        {**_mark(2, 1, 90), "horizon_minutes": 30},
        _mark(3, 1, 80, lag=20),
        _mark(4, 2, 100),
    ]
    report = daily_scorecard.build_daily_scorecard("2026-09-17", trades=trades, marks=marks, max_mark_lag_minutes=10)
    assert report["ready_ideas"] == 1
    assert report["option_marks"]["count"] == 1
    assert report["option_marks"]["average_return_pct"] == 20.0
    assert report["quality_state"] == "COLLECTING"


def test_daily_scorecard_flags_weak_option_session(monkeypatch):
    monkeypatch.setattr(daily_scorecard, "get_signal", lambda signal_id: None)
    trades = [_trade(i, symbol) for i, symbol in enumerate(["SPY", "QQQ", "NVDA"], 1)]
    marks = [_mark(1, 1, -30), _mark(2, 2, -20), _mark(3, 3, 5)]
    report = daily_scorecard.build_daily_scorecard("2026-09-17", trades=trades, marks=marks)
    assert report["option_marks"]["positive_rate_pct"] == 33.3
    assert report["quality_state"] == "WEAK"
    assert "Keep current gates" not in report["next_session_note"]
