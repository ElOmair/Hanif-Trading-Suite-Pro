from shadow_trade_store import list_shadow_trades, record_ready_shadow_trade, shadow_trade_summary


def _payload(signal_id=101):
    return {
        "signal_id": signal_id,
        "symbol": "SPY",
        "technical": {"signal": "LONG", "price": 760.0, "entry_low": 759.0, "entry_high": 760.0},
        "fusion_score": {"direction": "LONG", "score": 84.0, "coverage_pct": 80.0},
        "execution_gate": {"state": "REVIEW_ENTRY", "entry_review_allowed": True},
        "trade_plan": {"entry_low": 759.0, "entry_high": 760.0, "stop": 757.0, "tp1": 763.0},
        "options": [
            {
                "symbol": "SPY260918C00760000",
                "strike": 760,
                "expiration": "2026-09-18",
                "bid": 2.10,
                "ask": 2.20,
            }
        ],
    }


def test_ready_shadow_trade_records_once_and_updates_delivery(monkeypatch, tmp_path):
    monkeypatch.setenv("MNT_SHADOW_TRADE_DB", str(tmp_path / "shadow.sqlite3"))
    monkeypatch.setenv("MNT_SHADOW_TRADES_ENABLED", "true")
    first_id = record_ready_shadow_trade(_payload(), discord_sent=False)
    second_id = record_ready_shadow_trade(_payload(), discord_sent=True)
    assert first_id == second_id
    rows = list_shadow_trades()
    assert len(rows) == 1
    assert rows[0]["discord_sent"] == 1
    assert rows[0]["option_symbol"] == "SPY260918C00760000"


def test_non_ready_payload_is_not_recorded(monkeypatch, tmp_path):
    monkeypatch.setenv("MNT_SHADOW_TRADE_DB", str(tmp_path / "shadow.sqlite3"))
    payload = _payload()
    payload["execution_gate"] = {"state": "WAIT", "entry_review_allowed": False}
    assert record_ready_shadow_trade(payload) is None
    assert list_shadow_trades() == []


def test_shadow_summary_links_to_signal_outcomes(monkeypatch, tmp_path):
    monkeypatch.setenv("MNT_SHADOW_TRADE_DB", str(tmp_path / "shadow.sqlite3"))
    record_ready_shadow_trade(_payload(101), discord_sent=True)
    record_ready_shadow_trade(_payload(102), discord_sent=False)
    record_ready_shadow_trade(_payload(103), discord_sent=True)

    labels = {101: "WIN", 102: "LOSS", 103: "AMBIGUOUS"}

    def lookup(signal_id):
        return {"outcome": {"calibration_label": labels[signal_id]}}

    summary = shadow_trade_summary(signal_lookup=lookup)
    assert summary["shadow_trades"] == 3
    assert summary["discord_delivered"] == 2
    assert summary["wins"] == 1
    assert summary["losses"] == 1
    assert summary["ambiguous"] == 1
    assert summary["target_first_win_rate_pct"] == 50.0
