from worker_health import build_worker_status, read_worker_status, write_worker_status


def test_healthy_status_summarizes_scan(tmp_path):
    results = [
        {"stage": "session_risk", "state": "NORMAL", "tripped": False, "enforced": False, "entry_review_blocked": False, "eligible_option_marks": 3, "ignored_timing_marks": 1},
        {"stage": "radar", "used": True, "cached": False, "stale": False, "shortlist": ["SPY", "NVDA"]},
        {
            "symbol": "SPY",
            "classification": {"state": "READY"},
            "sent": True,
            "shadow_trade_id": 1,
            "suppressed_by_rank": False,
        },
        {
            "symbol": "NVDA",
            "classification": {"state": "PRE_TRIGGER"},
            "sent": False,
            "suppressed_by_rank": True,
        },
        {
            "stage": "option_marks",
            "status": "ok",
            "due": 2,
            "quoted_contracts": 1,
            "marks_recorded": 2,
            "missing_quotes": 0,
            "feed": "indicative",
        },
        {
            "stage": "daily_scorecard",
            "status": "sent",
            "sent": True,
            "session_date_et": "2026-09-17",
            "quality_state": "MIXED",
            "ready_ideas": 4,
            "option_marks": 3,
        },
    ]
    status = build_worker_status(results, market_active=True)
    assert status["worker_state"] == "HEALTHY"
    assert status["fusion"]["attempted"] == 2
    assert status["fusion"]["successful"] == 2
    assert status["alerts"]["ready_candidates"] == 1
    assert status["alerts"]["pretrigger_candidates"] == 1
    assert status["alerts"]["discord_sent"] == 1
    assert status["shadow"]["ready_records_written"] == 1
    assert status["shadow"]["option_marks"]["marks_recorded"] == 2
    assert status["shadow"]["option_marks"]["feed"] == "indicative"
    assert status["session_risk"]["state"] == "NORMAL"
    assert status["session_risk"]["eligible_option_marks"] == 3
    assert status["session_risk"]["ignored_timing_marks"] == 1
    assert status["daily_scorecard"]["status"] == "sent"
    assert status["daily_scorecard"]["sent"] is True
    assert status["daily_scorecard"]["quality_state"] == "MIXED"


def test_risk_paused_status_is_explicit():
    status = build_worker_status(
        [
            {
                "stage": "session_risk",
                "state": "PAUSE_NEW_ALERTS",
                "tripped": True,
                "enforced": True,
                "entry_review_blocked": True,
                "ready_ideas_today": 8,
                "consecutive_bad_option_marks": 3,
                "reasons": ["risk limit"],
            }
        ],
        market_active=True,
    )
    assert status["worker_state"] == "RISK_PAUSED"
    assert status["session_risk"]["entry_review_blocked"] is True
    assert status["session_risk"]["ready_ideas_today"] == 8


def test_partial_status_when_some_fusion_requests_fail():
    status = build_worker_status(
        [
            {"stage": "radar", "used": True, "shortlist": ["SPY", "NVDA"]},
            {"symbol": "SPY", "classification": {"state": "WATCH"}},
            {"symbol": "NVDA", "error": "TimeoutException"},
        ],
        market_active=True,
    )
    assert status["worker_state"] == "PARTIAL"
    assert status["fusion"]["successful"] == 1
    assert status["fusion"]["errors"] == 1


def test_off_hours_and_loop_error_states():
    off = build_worker_status([], market_active=False)
    assert off["worker_state"] == "OFF_HOURS"
    assert off["daily_scorecard"]["sent"] is False
    error = build_worker_status([], market_active=True, loop_error="RuntimeError")
    assert error["worker_state"] == "ERROR"


def test_atomic_status_round_trip(tmp_path):
    path = tmp_path / "worker.json"
    payload = build_worker_status([], market_active=False)
    write_worker_status(payload, path)
    loaded = read_worker_status(path)
    assert loaded["worker_state"] == "OFF_HOURS"
    assert loaded["status_file"] == str(path)


def test_missing_status_is_explicit(tmp_path):
    loaded = read_worker_status(tmp_path / "missing.json")
    assert loaded["worker_state"] == "NO_HEARTBEAT"
