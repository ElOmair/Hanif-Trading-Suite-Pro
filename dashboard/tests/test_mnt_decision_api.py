import asyncio

import mnt_decision_api as decision_api


def base_payload():
    return {
        "symbol": "SPY",
        "technical": {"symbol": "SPY", "signal": "LONG", "price": 500.0, "technical_score_preview": 82.0, "rvol": 1.5},
        "kronos": {"final_bias": "BULLISH", "bias_agreement_pct": 80, "stability": "HIGH"},
        "gamma": {"available": False},
        "flow": {"available": False},
        "market_regime": {"available": True, "sentiment": "BULLISH", "score": 75},
        "fusion_score": {"score": 80.0, "coverage_pct": 60.0, "direction": "LONG"},
        "decision": {"decision": "CONFIRM"},
        "options": [{"symbol": "KRONOS-SPY-CALL", "bid": 2.0, "ask": 2.1, "score": 70}],
        "research_only": True,
    }


def sample_chain():
    return {"callExpDateMap": {"2026-10-16:29": {"500.0": [{
        "symbol": "SPY  261016C00500000",
        "putCall": "CALL",
        "strikePrice": 500.0,
        "expirationDate": "2026-10-16T20:00:00.000+00:00",
        "daysToExpiration": 29,
        "bid": 2.20,
        "ask": 2.30,
        "delta": 0.50,
        "volatility": 22.0,
        "totalVolume": 1200,
        "openInterest": 5000,
    }]}}}


def test_disconnected_schwab_keeps_existing_options(monkeypatch):
    monkeypatch.setattr(decision_api, "token_status", lambda: {"configured": False, "authorized": False, "refresh_token_valid": False})
    result = asyncio.run(decision_api._schwab_overlay(base_payload(), max_contract_cost=300))
    assert result["available"] is False
    assert result["preferred_contract_provider"] == "kronos"
    assert result["preferred_options"][0]["symbol"] == "KRONOS-SPY-CALL"


def test_portfolio_gate_blocks_conflicting_position():
    context = {"relationship": "CONFLICT", "risk_level": "LOW", "concentration_pct": 2}
    gate = decision_api._portfolio_gate(context)
    assert gate["state"] == "BLOCK_ADD"
    assert gate["allow_add"] is False


def test_portfolio_gate_blocks_high_concentration():
    context = {"relationship": "ALREADY_EXPOSED", "risk_level": "HIGH", "concentration_pct": 24}
    gate = decision_api._portfolio_gate(context)
    assert gate["state"] == "BLOCK_ADD"
    assert gate["allow_add"] is False


def test_market_data_only_schwab_still_becomes_preferred_contract_source(monkeypatch):
    monkeypatch.setattr(decision_api, "token_status", lambda: {"configured": True, "authorized": True, "refresh_token_valid": True})
    monkeypatch.setattr(decision_api, "accounts_enabled", lambda: False)

    async def should_not_request_positions():
        raise AssertionError("positions must not be requested in analysis-only mode")

    async def fake_chain(symbol, **kwargs):
        return sample_chain()

    monkeypatch.setattr(decision_api, "positions", should_not_request_positions)
    monkeypatch.setattr(decision_api, "option_chain", fake_chain)
    result = asyncio.run(decision_api._schwab_overlay(base_payload(), max_contract_cost=300))
    assert result["available"] is True
    assert result["market_data_available"] is True
    assert result["accounts_available"] is False
    assert result["analysis_mode"] == "MARKET_DATA_ONLY"
    assert result["portfolio_gate"]["state"] == "NOT_IN_USE"
    assert result["preferred_contract_provider"] == "schwab"
    assert result["preferred_options"]
    assert result["broker_adjusted_fusion_score"] is not None


def test_connected_schwab_with_accounts_adds_portfolio_gate(monkeypatch):
    monkeypatch.setattr(decision_api, "token_status", lambda: {"configured": True, "authorized": True, "refresh_token_valid": True})
    monkeypatch.setattr(decision_api, "accounts_enabled", lambda: True)

    async def fake_positions():
        return {
            "accounts": [
                {
                    "account": "••••1234",
                    "balances": {"liquidation_value": 10000, "buying_power": 5000},
                    "positions": [],
                }
            ]
        }

    async def fake_chain(symbol, **kwargs):
        return sample_chain()

    monkeypatch.setattr(decision_api, "positions", fake_positions)
    monkeypatch.setattr(decision_api, "option_chain", fake_chain)
    result = asyncio.run(decision_api._schwab_overlay(base_payload(), max_contract_cost=300))
    assert result["accounts_available"] is True
    assert result["portfolio_gate"]["state"] == "OK_NEW"
    assert result["preferred_contract_provider"] == "schwab"
    assert result["preferred_options"]
    assert result["broker_adjusted_fusion_score"] is not None


def test_broker_aware_endpoint_never_enables_orders(monkeypatch):
    async def fake_fusion(symbol, max_contract_cost=None):
        return base_payload()

    async def fake_overlay(payload, max_contract_cost):
        return {
            "available": False,
            "preferred_options": payload["options"],
            "preferred_contract_provider": "kronos",
            "broker_adjusted_fusion_score": None,
        }

    monkeypatch.setattr(decision_api, "kronos_fusion", fake_fusion)
    monkeypatch.setattr(decision_api, "_schwab_overlay", fake_overlay)
    result = asyncio.run(decision_api.broker_aware_decision("SPY", max_contract_cost=300))
    assert result["order_submission_enabled"] is False
    assert result["research_only"] is True
    assert result["preferred_contract_provider"] == "kronos"
