from stock_position_manager import build_stock_position_analysis, equity_quote_snapshot


def quote(last=192.5, bid=192.4, ask=192.6):
    return {"quote": {"lastPrice": last, "bidPrice": bid, "askPrice": ask, "mark": (bid + ask) / 2}}


def test_equity_quote_snapshot_prefers_mark_and_preserves_bid_ask():
    snap = equity_quote_snapshot(quote())
    assert snap["current"] == 192.5
    assert snap["bid"] == 192.4
    assert snap["ask"] == 192.6


def test_long_stock_position_reports_real_dollar_pnl_and_shares():
    item = {"symbol": "NVDA", "kind": "OPEN_STOCK", "direction": "LONG", "entry_price": 185.0, "shares": 4}
    result = build_stock_position_analysis(item, quote())
    assert result["shares"] == 4
    assert result["pnl"]["cost_basis"] == 740.0
    assert result["pnl"]["market_value"] == 770.0
    assert result["pnl"]["dollars"] == 29.6
    assert result["pnl"]["pct"] == 4.0
    assert result["management"]["state"] == "WORKING"


def test_fractional_shares_are_supported():
    item = {"symbol": "HOOD", "kind": "OPEN_STOCK", "direction": "LONG", "entry_price": 50.0, "shares": 1.25}
    result = build_stock_position_analysis(item, quote(last=55.0, bid=54.9, ask=55.1))
    assert result["shares"] == 1.25
    assert result["pnl"]["cost_basis"] == 62.5
    assert result["pnl"]["dollars"] == 6.13


def test_short_stock_position_reverses_pnl_math():
    item = {"symbol": "TSLA", "kind": "OPEN_STOCK", "direction": "SHORT", "entry_price": 100.0, "shares": 10}
    result = build_stock_position_analysis(item, quote(last=90.0, bid=89.9, ask=90.1))
    assert result["pnl"]["pct"] == 9.9
    assert result["pnl"]["dollars"] == 99.0
    assert result["key_levels"]["price_checkpoint_10"] == 90.0


def test_profit_protection_state_for_large_stock_gain():
    item = {"symbol": "NVDA", "kind": "OPEN_STOCK", "direction": "LONG", "entry_price": 100.0, "shares": 5}
    result = build_stock_position_analysis(item, quote(last=115.0, bid=114.9, ask=115.1))
    assert result["management"]["state"] == "PROTECT_PROFIT"
    assert result["key_levels"]["protect_profit_reference"] == 100.0


def test_kronos_conflict_forces_exit_review_even_when_stock_is_profitable():
    item = {"symbol": "NVDA", "kind": "OPEN_STOCK", "direction": "LONG", "entry_price": 100.0, "shares": 5}
    fusion = {
        "technical": {"signal": "SHORT", "recent_low": 110.0, "recent_high": 120.0},
        "kronos": {"final_bias": "BEARISH"},
        "decision": {"decision": "REJECT"},
        "trade_plan": {"stop": 109.0, "tp1": 121.0, "tp2": 126.0},
    }
    result = build_stock_position_analysis(item, quote(last=115.0, bid=114.9, ask=115.1), fusion=fusion)
    assert result["pnl"]["pct"] > 0
    assert result["thesis"]["conflict"] is True
    assert result["management"]["state"] == "EXIT_REVIEW"
    assert result["key_levels"]["underlying_invalidation"] == 109.0
    assert result["key_levels"]["underlying_target_1"] == 121.0
