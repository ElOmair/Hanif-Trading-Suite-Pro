from __future__ import annotations

from datetime import datetime, timezone

from risk_governor import build_execution_gate


def _technical(**overrides):
    data = {
        "signal": "LONG",
        "price": 100.0,
        "atr": 2.0,
        "entry_low": 99.5,
        "entry_high": 100.5,
    }
    data.update(overrides)
    return data


def test_clean_confirm_can_be_reviewed(monkeypatch) -> None:
    monkeypatch.setenv("MNT_MIN_REVIEW_SCORE", "62")
    monkeypatch.setenv("MNT_MIN_REVIEW_COVERAGE", "55")
    gate = build_execution_gate(
        technical=_technical(),
        fusion_score={"score": 82.0, "coverage_pct": 85.0},
        decision={"decision": "CONFIRM"},
        trade_plan={"entry_low": 99.5, "entry_high": 100.5},
        market_gate={"active": False},
        now=datetime(2026, 9, 16, 15, 0, tzinfo=timezone.utc),
    )
    assert gate["state"] == "REVIEW_ENTRY"
    assert gate["entry_review_allowed"] is True
    assert gate["order_authorized"] is False
    assert gate["blockers"] == []


def test_low_coverage_is_blocked(monkeypatch) -> None:
    monkeypatch.setenv("MNT_MIN_REVIEW_COVERAGE", "55")
    gate = build_execution_gate(
        technical=_technical(),
        fusion_score={"score": 90.0, "coverage_pct": 40.0},
        decision={"decision": "CONFIRM"},
        market_gate={"active": False},
    )
    assert gate["state"] == "BLOCKED"
    assert any(item["code"] == "LOW_COVERAGE" for item in gate["blockers"])


def test_no_chase_is_blocked(monkeypatch) -> None:
    monkeypatch.setenv("MNT_NO_CHASE_ATR", "0.25")
    gate = build_execution_gate(
        technical=_technical(price=101.2),
        fusion_score={"score": 88.0, "coverage_pct": 90.0},
        decision={"decision": "CONFIRM"},
        trade_plan={"entry_low": 99.5, "entry_high": 100.5},
        market_gate={"active": False},
    )
    assert gate["no_chase"]["limit"] == 101.0
    assert gate["no_chase"]["blocked"] is True
    assert any(item["code"] == "NO_CHASE" for item in gate["blockers"])


def test_unconfirmed_setup_waits_instead_of_reviewing() -> None:
    gate = build_execution_gate(
        technical=_technical(),
        fusion_score={"score": 80.0, "coverage_pct": 80.0},
        decision={"decision": "WATCH"},
        market_gate={"active": False},
    )
    assert gate["state"] == "WAIT"
    assert gate["entry_review_allowed"] is False
    assert gate["wait_conditions"][0]["code"] == "AWAIT_CONFIRMATION"


def test_setup_has_expiry_window(monkeypatch) -> None:
    monkeypatch.setenv("MNT_SETUP_TTL_MINUTES", "10")
    now = datetime(2026, 9, 16, 15, 0, tzinfo=timezone.utc)
    gate = build_execution_gate(
        technical=_technical(),
        fusion_score={"score": 82.0, "coverage_pct": 85.0},
        decision={"decision": "CONFIRM"},
        market_gate={"active": False},
        now=now,
    )
    assert gate["generated_at"] == "2026-09-16T15:00:00+00:00"
    assert gate["expires_at"] == "2026-09-16T15:10:00+00:00"
