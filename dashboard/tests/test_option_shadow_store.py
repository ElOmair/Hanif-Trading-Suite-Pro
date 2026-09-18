from datetime import datetime, timedelta, timezone

import option_shadow_store as option_store
import shadow_trade_store as shadow_store


def _ready_payload(symbol: str, signal_id: int, option_symbol: str, ask: float):
    return {
        "symbol": symbol,
        "signal_id": signal_id,
        "technical": {"signal": "LONG", "price": 100.0},
        "fusion_score": {"direction": "LONG", "score": 82, "coverage_pct": 80},
        "execution_gate": {"state": "REVIEW_ENTRY", "entry_review_allowed": True},
        "trade_plan": {"entry_low": 99.5, "entry_high": 100.5, "stop": 97.5, "tp1": 104.0},
        "options": [
            {
                "symbol": option_symbol,
                "strike": 100,
                "expiration": "2026-09-18",
                "bid": ask - 0.1,
                "ask": ask,
            }
        ],
    }


def test_record_mark_uses_bid_vs_entry_ask(monkeypatch, tmp_path):
    db = tmp_path / "shadow.sqlite3"
    monkeypatch.setenv("MNT_SHADOW_TRADE_DB", str(db))
    monkeypatch.setenv("MNT_SHADOW_TRADES_ENABLED", "true")

    trade_id = shadow_store.record_ready_shadow_trade(
        _ready_payload("SPY", 101, "SPY260918C00760000", 2.0)
    )
    due = {
        "shadow_trade_id": trade_id,
        "signal_id": 101,
        "option_symbol": "SPY260918C00760000",
        "entry_ask": 2.0,
        "horizon_minutes": 30,
        "actual_age_minutes": 31.0,
        "lag_minutes": 1.0,
    }
    option_store.record_option_mark(due, {"bid": 2.5, "ask": 2.6}, feed="indicative")
    marks = option_store.list_option_marks(trade_id)
    assert len(marks) == 1
    assert round(marks[0]["return_bid_vs_entry_ask_pct"], 2) == 25.0
    assert round(marks[0]["return_mid_vs_entry_ask_pct"], 2) == 27.5


def test_summary_is_symbol_scoped_and_counts_large_moves(monkeypatch, tmp_path):
    db = tmp_path / "shadow.sqlite3"
    monkeypatch.setenv("MNT_SHADOW_TRADE_DB", str(db))
    monkeypatch.setenv("MNT_SHADOW_TRADES_ENABLED", "true")

    spy_id = shadow_store.record_ready_shadow_trade(
        _ready_payload("SPY", 201, "SPY260918C00760000", 2.0)
    )
    nvda_id = shadow_store.record_ready_shadow_trade(
        _ready_payload("NVDA", 202, "NVDA260918C00200000", 1.0)
    )
    for trade_id, signal_id, symbol, entry, bid in [
        (spy_id, 201, "SPY260918C00760000", 2.0, 3.1),
        (nvda_id, 202, "NVDA260918C00200000", 1.0, 0.4),
    ]:
        option_store.record_option_mark(
            {
                "shadow_trade_id": trade_id,
                "signal_id": signal_id,
                "option_symbol": symbol,
                "entry_ask": entry,
                "horizon_minutes": 60,
                "actual_age_minutes": 61.0,
                "lag_minutes": 1.0,
            },
            {"bid": bid, "ask": bid + 0.1},
            feed="indicative",
        )

    spy = option_store.option_mark_summary(symbol="SPY")
    nvda = option_store.option_mark_summary(symbol="NVDA")
    assert spy["horizons"]["60"]["count"] == 1
    assert spy["horizons"]["60"]["gain_50pct_or_more_count"] == 1
    assert nvda["horizons"]["60"]["loss_50pct_or_worse_count"] == 1


def test_due_marks_only_include_same_session_and_unmarked_horizons(monkeypatch, tmp_path):
    db = tmp_path / "shadow.sqlite3"
    monkeypatch.setenv("MNT_SHADOW_TRADE_DB", str(db))
    monkeypatch.setenv("MNT_SHADOW_TRADES_ENABLED", "true")

    trade_id = shadow_store.record_ready_shadow_trade(
        _ready_payload("SPY", 301, "SPY260918C00760000", 2.0)
    )
    now = datetime.now(timezone.utc)
    created = now - timedelta(minutes=35)
    with shadow_store._connect() as connection:
        connection.execute(
            "UPDATE mnt_shadow_trades SET created_at = ? WHERE id = ?",
            (created.isoformat(), trade_id),
        )
        connection.commit()

    due = option_store.due_option_marks(now=now, horizons=(15, 30, 60))
    assert [row["horizon_minutes"] for row in due] == [30, 15]
    assert due[0]["created_at"] == created.isoformat()
    option_store.record_option_mark(due[0], {"bid": 2.1, "ask": 2.2})
    due_again = option_store.due_option_marks(now=now, horizons=(15, 30, 60))
    assert [row["horizon_minutes"] for row in due_again] == [15]


def test_summary_rejects_stale_source_quote_even_when_collector_lag_is_small(monkeypatch, tmp_path):
    db = tmp_path / "shadow.sqlite3"
    monkeypatch.setenv("MNT_SHADOW_TRADE_DB", str(db))
    monkeypatch.setenv("MNT_SHADOW_TRADES_ENABLED", "true")

    trade_id = shadow_store.record_ready_shadow_trade(
        _ready_payload("SPY", 401, "SPY260918C00760000", 2.0)
    )
    created = datetime(2026, 9, 17, 14, 0, tzinfo=timezone.utc)
    due = {
        "shadow_trade_id": trade_id,
        "signal_id": 401,
        "option_symbol": "SPY260918C00760000",
        "entry_ask": 2.0,
        "created_at": created.isoformat(),
        "horizon_minutes": 60,
        "actual_age_minutes": 61.0,
        "lag_minutes": 1.0,
    }
    option_store.record_option_mark(
        due,
        {"bid": 2.4, "ask": 2.5, "timestamp": "2026-09-17T14:20:00+00:00"},
        marked_at=datetime(2026, 9, 17, 15, 1, tzinfo=timezone.utc),
    )
    mark = option_store.list_option_marks(trade_id)[0]
    assert mark["quote_age_minutes"] == 20.0
    assert mark["quote_horizon_error_minutes"] == 40.0
    summary = option_store.option_mark_summary(symbol="SPY", max_lag_minutes=10)
    assert summary["marks_total"] == 1
    assert summary["horizons"]["60"]["count"] == 0


def test_summary_accepts_source_quote_close_to_requested_horizon(monkeypatch, tmp_path):
    db = tmp_path / "shadow.sqlite3"
    monkeypatch.setenv("MNT_SHADOW_TRADE_DB", str(db))
    monkeypatch.setenv("MNT_SHADOW_TRADES_ENABLED", "true")

    trade_id = shadow_store.record_ready_shadow_trade(
        _ready_payload("QQQ", 402, "QQQ260918C00600000", 1.0)
    )
    created = datetime(2026, 9, 17, 14, 0, tzinfo=timezone.utc)
    option_store.record_option_mark(
        {
            "shadow_trade_id": trade_id,
            "signal_id": 402,
            "option_symbol": "QQQ260918C00600000",
            "entry_ask": 1.0,
            "created_at": created.isoformat(),
            "horizon_minutes": 60,
            "actual_age_minutes": 66.0,
            "lag_minutes": 6.0,
        },
        {"bid": 1.2, "ask": 1.3, "timestamp": "2026-09-17T15:03:00+00:00"},
        marked_at=datetime(2026, 9, 17, 15, 6, tzinfo=timezone.utc),
    )
    summary = option_store.option_mark_summary(symbol="QQQ", max_lag_minutes=10)
    assert summary["horizons"]["60"]["count"] == 1
    assert summary["horizons"]["60"]["average_return_pct"] == 20.0
