from option_position_manager import (
    build_option_position_analysis,
    find_exact_contract,
    option_spec_from_focus,
    parse_occ_symbol,
)


def sample_chain():
    return {
        "underlyingPrice": 70.0,
        "callExpDateMap": {
            "2026-10-16:28": {
                "65.0": [
                    {
                        "symbol": "HOOD  261016C00065000",
                        "description": "HOOD 10/16/2026 65.00 C",
                        "putCall": "CALL",
                        "strikePrice": 65.0,
                        "bid": 2.50,
                        "ask": 2.60,
                        "mark": 2.55,
                        "last": 2.54,
                        "daysToExpiration": 28,
                        "delta": 0.48,
                        "gamma": 0.04,
                        "theta": -0.05,
                        "vega": 0.08,
                        "volatility": 62.0,
                        "openInterest": 1200,
                        "totalVolume": 850,
                    }
                ]
            }
        },
        "putExpDateMap": {},
    }


def test_parse_occ_symbol_and_focus_spec():
    parsed = parse_occ_symbol("HOOD  261016C00065000")
    assert parsed["underlying"] == "HOOD"
    assert parsed["expiration"] == "2026-10-16"
    assert parsed["option_type"] == "CALL"
    assert parsed["strike"] == 65.0

    spec = option_spec_from_focus({
        "symbol": "HOOD",
        "kind": "OPEN_OPTION",
        "entry_price": 2.0,
        "quantity": 2,
        "contract": "HOOD  261016C00065000",
    })
    assert spec["option_type"] == "CALL"
    assert spec["strike"] == 65.0
    assert spec["expiration"] == "2026-10-16"
    assert spec["quantity"] == 2


def test_find_exact_contract_from_live_chain():
    spec = {
        "option_type": "CALL",
        "strike": 65.0,
        "expiration": "2026-10-16",
        "contract_symbol": None,
    }
    contract = find_exact_contract(sample_chain(), spec)
    assert contract is not None
    assert contract["symbol"].strip().startswith("HOOD")
    assert contract["bid"] == 2.50


def test_profitable_option_becomes_protect_profit_with_real_exit_pnl():
    item = {
        "symbol": "HOOD",
        "kind": "OPEN_OPTION",
        "entry_price": 2.0,
        "option_type": "CALL",
        "strike": 65.0,
        "expiration": "2026-10-16",
        "quantity": 2,
    }
    contract = find_exact_contract(sample_chain(), option_spec_from_focus(item))
    fusion = {
        "technical": {"signal": "LONG", "recent_low": 67.5},
        "kronos": {"final_bias": "BULLISH"},
        "decision": {"decision": "CONFIRM"},
        "trade_plan": {"stop": 67.25, "tp1": 72.0, "tp2": 74.0},
    }
    result = build_option_position_analysis(item, contract, underlying_price=70.0, fusion=fusion)
    assert result["pnl"]["exit_pct"] == 25.0
    assert result["pnl"]["exit_dollars"] == 100.0
    assert result["management"]["state"] == "PROTECT_PROFIT"
    assert result["key_levels"]["underlying_invalidation"] == 67.25
    assert result["key_levels"]["underlying_target_1"] == 72.0
    assert result["thesis"]["conflict"] is False


def test_opposing_underlying_thesis_overrides_open_profit():
    item = {
        "symbol": "HOOD",
        "kind": "OPEN_OPTION",
        "entry_price": 2.0,
        "option_type": "CALL",
        "strike": 65.0,
        "expiration": "2026-10-16",
        "quantity": 1,
    }
    contract = find_exact_contract(sample_chain(), option_spec_from_focus(item))
    fusion = {
        "technical": {"signal": "SHORT", "recent_high": 71.0, "recent_low": 67.5},
        "kronos": {"final_bias": "BEARISH"},
        "decision": {"decision": "REJECT"},
        "trade_plan": {},
    }
    result = build_option_position_analysis(item, contract, underlying_price=70.0, fusion=fusion)
    assert result["management"]["state"] == "EXIT_REVIEW"
    assert result["thesis"]["conflict"] is True
    assert len(result["thesis"]["conflict_reasons"]) >= 2


def test_losing_option_reports_recovery_needed_not_magic_profit_target():
    item = {
        "symbol": "HOOD",
        "kind": "OPEN_OPTION",
        "entry_price": 3.0,
        "option_type": "CALL",
        "strike": 65.0,
        "expiration": "2026-10-16",
        "quantity": 1,
    }
    contract = find_exact_contract(sample_chain(), option_spec_from_focus(item))
    result = build_option_position_analysis(item, contract, underlying_price=70.0)
    assert result["pnl"]["exit_pct"] < 0
    assert result["pnl"]["recovery_needed_pct"] > 0
    assert "average down" in result["management"]["next_step"].lower() or result["management"]["state"] == "UNDER_PRESSURE"
