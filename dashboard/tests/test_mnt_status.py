from datetime import datetime, timedelta, timezone

from mnt_status import operational_status


def _heartbeat(state="HEALTHY", age_seconds=30):
    now = datetime(2026, 9, 17, 0, 0, tzinfo=timezone.utc)
    return now, {
        "worker_state": state,
        "heartbeat_at": (now - timedelta(seconds=age_seconds)).isoformat(),
        "market_scan_active": True,
        "radar": {"shortlist": ["SPY"]},
        "fusion": {"attempted": 1, "successful": 1, "errors": 0},
        "alerts": {"discord_sent": 0},
        "shadow": {"ready_records_written": 0},
    }


def test_recent_healthy_heartbeat_is_ok():
    now, heartbeat = _heartbeat("HEALTHY", 30)
    report = operational_status(heartbeat, now=now, stale_after_seconds=180)
    assert report["overall"] == "OK"
    assert report["heartbeat_stale"] is False


def test_old_heartbeat_requires_attention_even_if_last_state_was_healthy():
    now, heartbeat = _heartbeat("HEALTHY", 600)
    report = operational_status(heartbeat, now=now, stale_after_seconds=180)
    assert report["overall"] == "ATTENTION"
    assert report["heartbeat_stale"] is True


def test_partial_worker_is_degraded_not_dead():
    now, heartbeat = _heartbeat("PARTIAL", 20)
    report = operational_status(heartbeat, now=now, stale_after_seconds=180)
    assert report["overall"] == "DEGRADED"


def test_off_hours_recent_heartbeat_is_ok():
    now, heartbeat = _heartbeat("OFF_HOURS", 20)
    heartbeat["market_scan_active"] = False
    report = operational_status(heartbeat, now=now, stale_after_seconds=180)
    assert report["overall"] == "OK"


def test_missing_heartbeat_needs_attention():
    now = datetime(2026, 9, 17, 0, 0, tzinfo=timezone.utc)
    report = operational_status({"worker_state": "NO_HEARTBEAT"}, now=now, stale_after_seconds=180)
    assert report["overall"] == "ATTENTION"
