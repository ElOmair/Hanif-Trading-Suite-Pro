from datetime import datetime
from zoneinfo import ZoneInfo

from mnt_alert_worker import AlertState, market_scan_active


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
