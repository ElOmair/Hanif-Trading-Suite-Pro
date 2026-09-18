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
            "option_evidence": {"eligible_trades": 3, "measured_trades": 3, "missing_eligible_trades": 0, "completeness_pct": 100.0, "complete": True},
            "option_marks": {"count": 3, "average_return_pct": 5.5, "positive_rate_pct": 66.7},
            "best_option": {"underlying": "NVDA", "direction": "LONG", "return_pct": 35},
            "worst_option": {"underlying": "TSLA", "direction": "SHORT", "return_pct": -20},
            "next_session_note": "Keep current gates.",
        }
    )
    text = message["embeds"][0]["description"]
    title = message["embeds"][0]["title"]
    assert "NVDA" in text
    assert "TSLA" in text
    assert "3/3 eligible ideas measured" in text
    assert "Keep current gates" in text
    assert "No brokerage orders" in text
    assert "PARTIAL" not in title


def test_partial_evidence_is_explicit_in_scorecard_title_and_body():
    message = alert.build_scorecard_message(
        {
            "session_date_et": "2026-09-17",
            "quality_state": "COLLECTING",
            "ready_ideas": 3,
            "long_ideas": 2,
            "short_ideas": 1,
            "discord_delivered": 3,
            "underlying_outcomes": {"wins": 0, "losses": 0},
            "option_horizon_minutes": 60,
            "option_evidence": {"eligible_trades": 3, "measured_trades": 2, "missing_eligible_trades": 1, "completeness_pct": 66.7, "complete": False},
            "option_marks": {"count": 2, "average_return_pct": 2.5, "positive_rate_pct": 50.0},
            "next_session_note": "Keep collecting shadow evidence.",
        }
    )
    assert "PARTIAL" in message["embeds"][0]["title"]
    text = message["embeds"][0]["description"]
    assert "2/3 eligible ideas measured" in text
    assert "Partial evidence" in text


def test_disabled_scorecard_does_not_send(monkeypatch):
    monkeypatch.setenv("MNT_EOD_SCORECARD_ENABLED", "false")

    class Client:
        async def post(self, *args, **kwargs):
            raise AssertionError("post should not be called")

    import asyncio

    result = asyncio.run(alert.maybe_send_daily_scorecard(Client(), datetime(2026, 9, 17, 17, 0, tzinfo=ET)))
    assert result["status"] == "disabled"
    assert result["sent"] is False


def test_no_activity_session_is_recorded_without_discord_and_not_retried(monkeypatch, tmp_path):
    monkeypatch.setenv("MNT_EOD_SCORECARD_ENABLED", "true")
    monkeypatch.setenv("MNT_DISCORD_WEBHOOK_URL", "https://discord.invalid/webhook")
    monkeypatch.setenv("MNT_EOD_SCORECARD_HOUR_ET", "16")
    monkeypatch.setenv("MNT_EOD_SCORECARD_MINUTE_ET", "15")
    state_file = tmp_path / "scorecard-state.json"
    monkeypatch.setenv("MNT_EOD_SCORECARD_STATE_FILE", str(state_file))
    monkeypatch.setattr(
        alert,
        "build_daily_scorecard",
        lambda *args, **kwargs: {"ready_ideas": 0, "option_marks": {"count": 0}},
    )

    class Client:
        async def post(self, *args, **kwargs):
            raise AssertionError("empty session must not send Discord")

    import asyncio

    when = datetime(2026, 9, 17, 16, 20, tzinfo=ET)
    first = asyncio.run(alert.maybe_send_daily_scorecard(Client(), when))
    assert first["status"] == "no_activity"
    assert first["sent"] is False
    saved = alert._load_state(state_file)
    assert saved["last_sent_session_date"] == "2026-09-17"
    assert saved["status"] == "no_activity"
    due_again, _ = alert.due_for_delivery(when, saved)
    assert due_again is False
