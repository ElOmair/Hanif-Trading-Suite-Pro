from datetime import datetime
from zoneinfo import ZoneInfo

import daily_scorecard_alert as alert


ET = ZoneInfo("America/New_York")


def test_scorecard_delivery_is_due_once_after_configured_time(monkeypatch):
    monkeypatch.setenv("MNT_EOD_SCORECARD_HOUR_ET", "16")
    monkeypatch.setenv("MNT_EOD_SCORECARD_MINUTE_ET", "15")
    before = datetime(2026, 9, 17, 16, 14, tzinfo=ET)
    after = datetime(2026, 9, 17, 16, 15, tzinfo=ET)
    due_before, _ = alert.due_for_delivery(before, {})
    due_after, session = alert.due_for_delivery(after, {})
    due_again, _ = alert.due_for_delivery(after, {"last_sent_session_date": session})
    assert due_before is False
    assert due_after is True
    assert session == "2026-09-17"
    assert due_again is False


def test_scorecard_delivery_is_not_due_on_weekend():
    due, session = alert.due_for_delivery(datetime(2026, 9, 19, 17, 0, tzinfo=ET), {})
    assert due is False
    assert session == "2026-09-19"


def test_scorecard_message_is_shadow_only_and_has_best_worst():
    message = alert.build_scorecard_message(
        {
            "session_date_et": "2026-09-17",
            "quality_state": "MIXED",
            "ready_ideas": 4,
            "long_ideas": 3,
            "short_ideas": 1,
            "discord_delivered": 3,
            "underlying_outcomes": {"wins": 2, "losses": 1, "target_first_win_rate_pct": 66.7},
            "option_horizon_minutes": 60,
            "option_marks": {"count": 3, "average_return_pct": 5.5, "positive_rate_pct": 66.7},
            "best_option": {"underlying": "NVDA", "direction": "LONG", "return_pct": 35},
            "worst_option": {"underlying": "TSLA", "direction": "SHORT", "return_pct": -20},
            "next_session_note": "Keep current gates.",
        }
    )
    text = message["embeds"][0]["description"]
    assert "NVDA" in text
    assert "TSLA" in text
    assert "Keep current gates" in text
    assert "No brokerage orders" in text


def test_disabled_scorecard_does_not_send(monkeypatch):
    monkeypatch.setenv("MNT_EOD_SCORECARD_ENABLED", "false")

    class Client:
        async def post(self, *args, **kwargs):
            raise AssertionError("post should not be called")

    import asyncio

    result = asyncio.run(alert.maybe_send_daily_scorecard(Client(), datetime(2026, 9, 17, 17, 0, tzinfo=ET)))
    assert result["status"] == "disabled"
    assert result["sent"] is False
