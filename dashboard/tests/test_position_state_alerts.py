from pathlib import Path

from position_state_alerts import PositionAlertState, build_position_alert_message


def test_position_alert_state_baselines_then_notifies_on_transition(monkeypatch, tmp_path):
    monkeypatch.setenv("MNT_POSITION_ALERT_COOLDOWN_SECONDS", "0")
    state = PositionAlertState(Path(tmp_path) / "position-state.json")

    first = state.observe("HOOD", "OPEN_OPTION", "WORKING")
    assert first["baseline"] is True
    assert first["notify"] is False

    same = state.observe("HOOD", "OPEN_OPTION", "WORKING")
    assert same["changed"] is False
    assert same["notify"] is False

    changed = state.observe("HOOD", "OPEN_OPTION", "PROTECT_PROFIT")
    assert changed["previous_state"] == "WORKING"
    assert changed["changed"] is True
    assert changed["notify"] is True


def test_urgent_position_state_bypasses_cooldown(monkeypatch, tmp_path):
    monkeypatch.setenv("MNT_POSITION_ALERT_COOLDOWN_SECONDS", "3600")
    state = PositionAlertState(Path(tmp_path) / "position-state.json")
    state.observe("NVDA", "OPEN_STOCK", "WORKING")
    first_change = state.observe("NVDA", "OPEN_STOCK", "PROTECT_PROFIT")
    assert first_change["notify"] is True
    urgent = state.observe("NVDA", "OPEN_STOCK", "EXIT_REVIEW")
    assert urgent["notify"] is True


def test_discord_position_alert_contains_transition_pnl_and_next_step():
    item = {"symbol": "NVDA", "kind": "OPEN_STOCK"}
    analysis = {
        "current": {"price": 195.0, "exit_reference": 194.9},
        "pnl": {"pct": 12.4, "dollars": 91.0},
        "management": {
            "state": "PROTECT_PROFIT",
            "headline": "The position is working; protect the gain.",
            "next_step": "Tighten risk while the underlying remains constructive.",
        },
    }
    message = build_position_alert_message(item=item, analysis=analysis, previous_state="WORKING")
    assert "NVDA" in message["content"]
    embed = message["embeds"][0]
    assert "PROTECT PROFIT" in embed["title"]
    fields = {field["name"]: field["value"] for field in embed["fields"]}
    assert fields["State change"] == "WORKING → PROTECT_PROFIT"
    assert "+12.4%" in fields["P/L"]
    assert "Tighten risk" in fields["Next step"]
