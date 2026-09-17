from schwab_portfolio import build_symbol_context, option_side, underlying_symbol


def _portfolio():
    return {
        "accounts": [
            {
                "account": "••••1234",
                "balances": {"liquidation_value": 10000.0, "buying_power": 4200.0},
                "positions": [
                    {
                        "symbol": "NVDA",
                        "asset_type": "EQUITY",
                        "long_quantity": 5,
                        "short_quantity": 0,
                        "average_price": 175.0,
                        "market_value": 925.0,
                    },
                    {
                        "symbol": "SPY  261016C00760000",
                        "asset_type": "OPTION",
                        "long_quantity": 1,
                        "short_quantity": 0,
                        "average_price": 2.25,
                        "market_value": 300.0,
                    },
                    {
                        "symbol": "QQQ  261016P00600000",
                        "asset_type": "OPTION",
                        "long_quantity": 1,
                        "short_quantity": 0,
                        "average_price": 2.00,
                        "market_value": 240.0,
                    },
                ],
            }
        ]
    }


def test_underlying_and_option_side_parse_schwab_occ_symbols():
    assert underlying_symbol("SPY  261016C00760000", "OPTION") == "SPY"
    assert option_side("SPY  261016C00760000") == "CALL"
    assert option_side("QQQ  261016P00600000") == "PUT"
    assert underlying_symbol("NVDA", "EQUITY") == "NVDA"


def test_long_setup_knows_user_is_already_bullish_nvda():
    result = build_symbol_context(_portfolio(), "NVDA", intended_direction="LONG")
    assert result["relationship"] == "ALREADY_EXPOSED"
    assert result["exposure_state"] == "BULLISH"
    assert result["existing_position_count"] == 1
    assert result["buying_power"] == 4200.0
    assert result["concentration_pct"] == 9.25


def test_short_setup_flags_conflict_with_existing_long_call():
    result = build_symbol_context(_portfolio(), "SPY", intended_direction="SHORT")
    assert result["relationship"] == "CONFLICT"
    assert result["exposure_state"] == "BULLISH"
    assert result["positions"][0]["option_side"] == "CALL"


def test_long_put_counts_as_bearish_exposure():
    result = build_symbol_context(_portfolio(), "QQQ", intended_direction="SHORT")
    assert result["relationship"] == "ALREADY_EXPOSED"
    assert result["exposure_state"] == "BEARISH"


def test_new_symbol_returns_new_relationship():
    result = build_symbol_context(_portfolio(), "AAPL", intended_direction="LONG")
    assert result["relationship"] == "NEW"
    assert result["existing_position_count"] == 0
