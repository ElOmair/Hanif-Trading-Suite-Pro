from schwab_position_manager import build_portfolio_reviews, review_position


def option_row(**overrides):
    row = {
        "symbol": "SPY  261016C00500000",
        "asset_type": "OPTION",
        "long_quantity": 1,
        "short_quantity": 0,
        "average_price": 2.00,
        "average_long_price": 2.00,
        "market_value": 260.0,
        "unrealized_profit_loss": 60.0,
        "current_day_profit_loss": 20.0,
        "current_day_profit_loss_pct": 8.0,
    }
    row.update(overrides)
    return row


def test_profitable_option_suggests_partial_profit():
    result = review_position(option_row(), liquidation_value=5000, technical={"signal": "LONG"})
    assert result["estimated_open_return_pct"] == 30.0
    assert result["state"] == "TAKE_SOME_PROFIT"
    assert result["research_only"] is True


def test_losing_option_against_technical_direction_is_exit_review():
    result = review_position(
        option_row(unrealized_profit_loss=-40.0, market_value=160.0),
        liquidation_value=5000,
        technical={"signal": "SHORT"},
    )
    assert result["estimated_open_return_pct"] == -20.0
    assert result["state"] == "REVIEW_EXIT"


def test_high_concentration_blocks_add_when_otherwise_aligned():
    row = {
        "symbol": "NVDA",
        "asset_type": "EQUITY",
        "long_quantity": 10,
        "short_quantity": 0,
        "average_price": 100,
        "market_value": 2500,
        "unrealized_profit_loss": 50,
    }
    result = review_position(row, liquidation_value=10000, technical={"signal": "LONG"})
    assert result["concentration_pct"] == 25.0
    assert result["state"] == "DO_NOT_ADD"


def test_portfolio_reviews_prioritize_attention_states():
    portfolio = {
        "accounts": [
            {
                "account": "••••1234",
                "balances": {"liquidation_value": 10000},
                "positions": [
                    option_row(symbol="SPY  261016C00500000", unrealized_profit_loss=60),
                    {
                        "symbol": "MSFT",
                        "asset_type": "EQUITY",
                        "long_quantity": 2,
                        "short_quantity": 0,
                        "average_price": 400,
                        "market_value": 820,
                        "unrealized_profit_loss": 20,
                    },
                ],
            }
        ]
    }
    report = build_portfolio_reviews(
        portfolio,
        technical_by_symbol={"SPY": {"signal": "LONG"}, "MSFT": {"signal": "LONG"}},
    )
    assert report["position_count"] == 2
    assert report["attention_count"] == 1
    assert report["reviews"][0]["state"] == "TAKE_SOME_PROFIT"
    assert report["order_submission_enabled"] is False
