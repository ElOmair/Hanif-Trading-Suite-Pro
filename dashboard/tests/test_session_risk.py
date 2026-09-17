from datetime import datetime, timezone

from session_risk import evaluate_session_risk


def _trade(trade_id: int, created_at: str):
    return {"id": trade_id, "created_at": created_at}


def _mark(mark_id: int, trade_id: int, value: float, horizon: int = 60):
    return {
        "id": mark_id,
        "shadow_trade_id": trade_id,
        "horizon_minutes": horizon,
        "return_bid_vs_entry_ask_pct": value,
    }


def test_ready_count_trips_advisory_but_does_not_block_by_default():
    now = datetime(2026, 9, 16, 18, 0, tzinfo=timezone.utc)
    trades = [_trade(i, "2026-09-16T15:00:00+00:00") for i in range(1, 9)]
    result = evaluate_session_risk(trades, [], now=now, max_ready_alerts=8, enforce=False)
    assert result["tripped"] is True
    assert result["state"] == "PAUSE_NEW_ALERTS"
    assert result["entry_review_blocked"] is False


def test_enforcement_blocks_when_limit_is_hit():
    now = datetime(2026, 9, 16, 18, 0, tzinfo=timezone.utc)
    trades = [_trade(i, "2026-09-16T15:00:00+00:00") for i in range(1, 9)]
    result = evaluate_session_risk(trades, [], now=now, max_ready_alerts=8, enforce=True)
    assert result["entry_review_blocked"] is True


def test_three_consecutive_bad_option_marks_trip_risk():
    now = datetime(2026, 9, 16, 18, 0, tzinfo=timezone.utc)
    trades = [_trade(i, "2026-09-16T15:00:00+00:00") for i in range(1, 5)]
    marks = [
        _mark(1, 1, 10.0),
        _mark(2, 2, -30.0),
        _mark(3, 3, -40.0),
        _mark(4, 4, -25.0),
    ]
    result = evaluate_session_risk(
        trades,
        marks,
        now=now,
        max_ready_alerts=20,
        bad_option_return_pct=-25.0,
        max_consecutive_bad_marks=3,
    )
    assert result["tripped"] is True
    assert result["consecutive_bad_option_marks"] == 3


def test_good_latest_mark_resets_consecutive_loss_streak():
    now = datetime(2026, 9, 16, 18, 0, tzinfo=timezone.utc)
    trades = [_trade(i, "2026-09-16T15:00:00+00:00") for i in range(1, 5)]
    marks = [
        _mark(1, 1, -30.0),
        _mark(2, 2, -40.0),
        _mark(3, 3, -25.0),
        _mark(4, 4, 5.0),
    ]
    result = evaluate_session_risk(trades, marks, now=now, max_ready_alerts=20)
    assert result["tripped"] is False
    assert result["consecutive_bad_option_marks"] == 0


def test_prior_day_trades_do_not_count_against_today():
    now = datetime(2026, 9, 16, 18, 0, tzinfo=timezone.utc)
    trades = [
        _trade(1, "2026-09-15T15:00:00+00:00"),
        _trade(2, "2026-09-16T15:00:00+00:00"),
    ]
    result = evaluate_session_risk(trades, [], now=now, max_ready_alerts=2)
    assert result["ready_ideas_today"] == 1
    assert result["tripped"] is False


def test_prior_day_bad_marks_do_not_trip_when_today_has_no_ready_ideas():
    now = datetime(2026, 9, 16, 18, 0, tzinfo=timezone.utc)
    trades = [
        _trade(1, "2026-09-15T15:00:00+00:00"),
        _trade(2, "2026-09-15T16:00:00+00:00"),
        _trade(3, "2026-09-15T17:00:00+00:00"),
    ]
    marks = [_mark(1, 1, -40.0), _mark(2, 2, -35.0), _mark(3, 3, -30.0)]
    result = evaluate_session_risk(trades, marks, now=now, max_ready_alerts=20)
    assert result["ready_ideas_today"] == 0
    assert result["consecutive_bad_option_marks"] == 0
    assert result["tripped"] is False
