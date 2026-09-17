from datetime import datetime, timedelta, timezone

from edge_slices import summarize_edge_slices


def _row(index: int, symbol: str, direction: str, label: str, hour_utc: int, score: float = 80):
    stamp = datetime(2026, 9, 17, hour_utc, 0, tzinfo=timezone.utc) + timedelta(minutes=index)
    return {
        "created_at": stamp.isoformat(),
        "symbol": symbol,
        "direction": direction,
        "score": score,
        "outcome": {"calibration_label": label},
    }


def test_edge_slices_measure_symbol_direction_and_session_without_auto_filtering():
    rows = []
    # 10:00 ET open: SPY LONG wins 8/10.
    for i in range(10):
        rows.append(_row(i, "SPY", "LONG", "WIN" if i < 8 else "LOSS", 14))
    # 14:00 ET afternoon: TSLA SHORT wins 2/10.
    for i in range(10):
        rows.append(_row(i, "TSLA", "SHORT", "WIN" if i < 2 else "LOSS", 18, score=70))

    report = summarize_edge_slices(rows, min_samples=8)
    assert report["resolved"] == 20
    assert report["baseline_win_rate_pct"] == 50.0
    symbols = {item["value"]: item for item in report["by_dimension"]["symbol"]}
    sessions = {item["value"]: item for item in report["by_dimension"]["session"]}
    assert symbols["SPY"]["win_rate_pct"] == 80.0
    assert symbols["SPY"]["state"] == "SUPPORTED"
    assert symbols["TSLA"]["win_rate_pct"] == 20.0
    assert symbols["TSLA"]["state"] == "CAUTION"
    assert sessions["OPEN"]["win_rate_pct"] == 80.0
    assert sessions["AFTERNOON"]["win_rate_pct"] == 20.0
    assert report["research_only"] is True
    assert "does not auto-block" in report["note"]


def test_small_slice_stays_insufficient_even_with_perfect_win_rate():
    rows = [_row(i, "NVDA", "LONG", "WIN", 14) for i in range(4)]
    report = summarize_edge_slices(rows, min_samples=8)
    nvda = next(item for item in report["by_dimension"]["symbol"] if item["value"] == "NVDA")
    assert nvda["win_rate_pct"] == 100.0
    assert nvda["state"] == "INSUFFICIENT"
    assert report["best_supported_slices"] == []


def test_pending_and_ambiguous_rows_do_not_enter_resolved_slices():
    rows = [
        _row(1, "SPY", "LONG", "WIN", 14),
        {**_row(2, "SPY", "LONG", "WIN", 14), "outcome": {"calibration_label": "AMBIGUOUS"}},
        {**_row(3, "SPY", "LONG", "WIN", 14), "outcome": {}},
    ]
    report = summarize_edge_slices(rows, min_samples=1)
    assert report["resolved"] == 1
    assert report["baseline_win_rate_pct"] == 100.0
