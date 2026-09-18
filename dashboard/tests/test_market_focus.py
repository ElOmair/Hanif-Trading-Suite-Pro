from market_focus import (
    build_priority_queue,
    rank_movers,
    rank_sectors,
    selected_sector_etfs,
)
from focused_alert_scan import _focus_universe, _shortlist_from_focus


def test_sector_ranking_finds_leader_and_laggard():
    rows = [
        {"symbol": "SMH", "score": 82, "momentum_30m_pct": 1.4, "rvol": 1.8},
        {"symbol": "XLF", "score": 52, "momentum_30m_pct": 0.1, "rvol": 1.0},
        {"symbol": "XLE", "score": 25, "momentum_30m_pct": -1.1, "rvol": 1.7},
    ]
    ranked = rank_sectors(rows, spy_momentum=0.2)
    assert ranked[0]["symbol"] == "SMH"
    assert ranked[-1]["symbol"] == "XLE"
    picked = selected_sector_etfs(ranked, leaders=1, laggards=1)
    assert picked == ["SMH", "XLE"]


def test_sector_aligned_mover_gets_priority_bonus():
    rows = [
        {"symbol": "AMD", "direction": "LONG", "rank_score": 78, "score": 78, "momentum_30m_pct": 1.2, "rvol": 2.0},
        {"symbol": "XOM", "direction": "LONG", "rank_score": 80, "score": 80, "momentum_30m_pct": 1.2, "rvol": 2.0},
    ]
    ranked = rank_movers(
        rows,
        sector_by_symbol={"AMD": "SMH", "XOM": "XLE"},
        sector_strength_by_etf={"SMH": 60, "XLE": -50},
    )
    assert ranked[0]["symbol"] == "AMD"
    assert ranked[0]["sector_aligned"] is True
    assert next(row for row in ranked if row["symbol"] == "XOM")["sector_aligned"] is False


def test_priority_queue_keeps_core_then_active_mag7_and_movers():
    mag7 = [
        {"symbol": "NVDA", "direction": "LONG", "rank_score": 90, "score": 90, "momentum_30m_pct": 1.5, "rvol": 2.0},
        {"symbol": "AAPL", "direction": "NEUTRAL", "rank_score": 0, "score": 51, "momentum_30m_pct": 0.1, "rvol": 0.8},
        {"symbol": "TSLA", "direction": "SHORT", "rank_score": 88, "score": 12, "momentum_30m_pct": -1.3, "rvol": 1.9},
    ]
    movers = [
        {"symbol": "AMD", "direction": "LONG", "score": 84, "rvol": 2.2, "focus_score": 105, "sector_aligned": True, "sector": "Semiconductors", "sector_etf": "SMH"},
        {"symbol": "XOM", "direction": "SHORT", "score": 22, "rvol": 1.8, "focus_score": 98, "sector_aligned": True, "sector": "Energy", "sector_etf": "XLE"},
    ]
    queue = build_priority_queue(mag7_snapshots=mag7, movers=movers, max_items=8, mag7_slots=2, mover_slots=4)
    symbols = [row["symbol"] for row in queue]
    assert symbols[:2] == ["SPY", "QQQ"]
    assert "NVDA" in symbols
    assert "TSLA" in symbols
    assert "AMD" in symbols
    assert "XOM" in symbols


def test_worker_focus_universe_includes_sector_names_and_dynamic_shortlist():
    universe = _focus_universe()
    assert "SPY" in universe
    assert "NVDA" in universe
    assert "AMD" in universe
    assert "XOM" in universe
    focus = {"priority_symbols": ["SPY", "QQQ", "NVDA", "AMD", "XOM"]}
    assert _shortlist_from_focus(focus, universe, limit=3) == ["SPY", "QQQ", "NVDA"]
