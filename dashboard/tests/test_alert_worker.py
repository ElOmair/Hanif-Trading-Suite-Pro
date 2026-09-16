import time
from datetime import datetime
from zoneinfo import ZoneInfo

from mnt_alert_worker import AlertState, market_scan_active, rank_alert_candidates, shortlist_from_radar


def test_market_scan_active_during_weekday_session(monkeypatch):
    monkeypatch.setenv("MNT_ALERT_START_MINUTE_ET", "565")
    monkeypatch.setenv("MNT_ALERT_END_MINUTE_ET", "965")
    et = ZoneInfo("America/New_York")
    assert market_scan_active(datetime(2026, 9, 16, 10, 0, tzinfo=et)) is True
    assert market_scan_active(datetime(2026, 9, 16, 18, 0, tzinfo=et)) is False


def test_ready_escalation_sends_even_after_pretrigger(tmp_path):
    state = AlertState(tmp_path / "state.json")
    pre = {"state": "PRE_TRIGGER", "score": 76, "coverage_pct": 70}
    ready = {"state": "READY", "score": 81, "coverage_pct": 75}
    assert state.should_send("SPY", pre, 900) is True
    state.mark_sent("SPY", pre)
    assert state.should_send("SPY", ready, 900) is True


def test_duplicate_pretrigger_is_suppressed(tmp_path):
    state = AlertState(tmp_path / "state.json")
    first = {"state": "PRE_TRIGGER", "score": 76, "coverage_pct": 70}
    same = {"state": "PRE_TRIGGER", "score": 78, "coverage_pct": 72}
    state.mark_sent("SPY", first)
    assert state.should_send("SPY", same, 900) is False


def test_watch_resets_pretrigger_so_new_setup_can_alert(tmp_path):
    state = AlertState(tmp_path / "state.json")
    pre = {"state": "PRE_TRIGGER", "score": 76, "coverage_pct": 70}
    state.mark_sent("SPY", pre)
    state.observe("SPY", {"state": "WATCH"})
    assert state.should_send("SPY", pre, 900) is True


def test_ready_alerts_rank_above_pretrigger():
    rows = [
        {"symbol": "NVDA", "classification": {"state": "PRE_TRIGGER", "score": 95, "coverage_pct": 90}},
        {"symbol": "SPY", "classification": {"state": "READY", "score": 78, "coverage_pct": 70}},
    ]
    ranked = rank_alert_candidates(rows)
    assert ranked[0]["symbol"] == "SPY"


def test_same_state_ranks_score_then_coverage():
    rows = [
        {"symbol": "A", "classification": {"state": "PRE_TRIGGER", "score": 80, "coverage_pct": 65}},
        {"symbol": "B", "classification": {"state": "PRE_TRIGGER", "score": 84, "coverage_pct": 60}},
        {"symbol": "C", "classification": {"state": "PRE_TRIGGER", "score": 84, "coverage_pct": 85}},
    ]
    ranked = rank_alert_candidates(rows)
    assert [row["symbol"] for row in ranked] == ["C", "B", "A"]


def test_radar_shortlist_balances_long_and_short():
    radar = {
        "longs": [
            {"symbol": "NVDA", "rank_score": 92},
            {"symbol": "AAPL", "rank_score": 85},
            {"symbol": "META", "rank_score": 80},
        ],
        "shorts": [
            {"symbol": "TSLA", "rank_score": 90},
            {"symbol": "AMD", "rank_score": 82},
            {"symbol": "COIN", "rank_score": 78},
        ],
    }
    selected = shortlist_from_radar(radar, ["NVDA", "AAPL", "META", "TSLA", "AMD", "COIN"], limit=4)
    assert selected == ["NVDA", "AAPL", "TSLA", "AMD"]


def test_radar_shortlist_filters_to_configured_symbols_and_fills_slots():
    radar = {
        "longs": [
            {"symbol": "NOTWATCHED", "rank_score": 99},
            {"symbol": "NVDA", "rank_score": 88},
            {"symbol": "AAPL", "rank_score": 84},
        ],
        "shorts": [{"symbol": "TSLA", "rank_score": 91}],
    }
    selected = shortlist_from_radar(radar, ["NVDA", "AAPL", "TSLA"], limit=3)
    assert selected == ["NVDA", "TSLA", "AAPL"]


def test_radar_failure_fallback_is_bounded():
    configured = ["SPY", "QQQ", "NVDA", "TSLA", "AAPL"]
    assert shortlist_from_radar(None, configured, limit=3) == ["SPY", "QQQ", "NVDA"]


def test_recent_pretrigger_stays_sticky(tmp_path):
    state = AlertState(tmp_path / "state.json")
    state.data = {
        "SPY": {"state": "PRE_TRIGGER", "score": 77, "sent_at": time.time() - 20},
        "NVDA": {"state": "PRE_TRIGGER", "score": 80, "sent_at": time.time() - 10},
        "TSLA": {"state": "READY", "score": 82, "sent_at": time.time() - 5},
    }
    sticky = state.active_pretrigger_symbols(["SPY", "NVDA", "TSLA"], limit=2)
    assert sticky == ["NVDA", "SPY"]


def test_pretrigger_to_no_chase_requires_stand_down(tmp_path):
    state = AlertState(tmp_path / "state.json")
    state.mark_sent("SPY", {"state": "PRE_TRIGGER", "score": 76, "coverage_pct": 70})
    assert state.needs_stand_down("SPY", {"state": "NO_CHASE"}) is True
    assert state.needs_stand_down("SPY", {"state": "READY"}) is False


def test_stale_alert_state_expires_and_does_not_suppress_new_setup(monkeypatch, tmp_path):
    monkeypatch.setenv("MNT_ALERT_STATE_MAX_AGE_SECONDS", "60")
    state = AlertState(tmp_path / "state.json")
    state.data["SPY"] = {
        "state": "PRE_TRIGGER",
        "score": 76,
        "coverage_pct": 70,
        "sent_at": time.time() - 120,
    }
    assert state.should_send("SPY", {"state": "PRE_TRIGGER", "score": 76, "coverage_pct": 70}, 900) is True
    assert "SPY" not in state.data
