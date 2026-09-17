from schwab_contracts import flatten_chain, rank_option_candidates


def _chain():
    return {
        "callExpDateMap": {
            "2026-10-16:29": {
                "760.0": [
                    {
                        "symbol": "SPY  261016C00760000",
                        "putCall": "CALL",
                        "strikePrice": 760.0,
                        "bid": 2.40,
                        "ask": 2.50,
                        "mark": 2.45,
                        "delta": 0.51,
                        "totalVolume": 800,
                        "openInterest": 4000,
                        "daysToExpiration": 29,
                        "volatility": 24.0,
                    }
                ],
                "765.0": [
                    {
                        "symbol": "SPY  261016C00765000",
                        "putCall": "CALL",
                        "strikePrice": 765.0,
                        "bid": 0.75,
                        "ask": 0.95,
                        "delta": 0.28,
                        "totalVolume": 5,
                        "openInterest": 20,
                        "daysToExpiration": 29,
                        "volatility": 30.0,
                    }
                ],
            }
        },
        "putExpDateMap": {
            "2026-10-16:29": {
                "750.0": [
                    {
                        "symbol": "SPY  261016P00750000",
                        "putCall": "PUT",
                        "strikePrice": 750.0,
                        "bid": 2.20,
                        "ask": 2.30,
                        "delta": -0.50,
                        "totalVolume": 900,
                        "openInterest": 3500,
                        "daysToExpiration": 29,
                        "volatility": 25.0,
                    }
                ]
            }
        },
    }


def test_flatten_chain_uses_directional_side():
    calls = flatten_chain(_chain(), "LONG")
    puts = flatten_chain(_chain(), "SHORT")
    assert len(calls) == 2
    assert len(puts) == 1
    assert calls[0]["expirationDateText"] == "2026-10-16"


def test_swing_rank_prefers_liquid_delta_aligned_contract():
    candidates = rank_option_candidates(
        _chain(),
        direction="LONG",
        max_contract_cost=300,
        style="swing",
        limit=3,
    )
    assert candidates[0]["symbol"] == "SPY  261016C00760000"
    assert candidates[0]["score"] > candidates[1]["score"]
    assert candidates[0]["provider"] == "schwab"
    assert candidates[0]["estimated_cost"] == 250.0
    assert candidates[0]["expiration"] == "2026-10-16"


def test_max_contract_cost_is_hard_filter():
    candidates = rank_option_candidates(
        _chain(),
        direction="LONG",
        max_contract_cost=100,
        style="swing",
        limit=3,
    )
    assert len(candidates) == 1
    assert candidates[0]["symbol"] == "SPY  261016C00765000"


def test_short_uses_puts():
    candidates = rank_option_candidates(
        _chain(),
        direction="SHORT",
        max_contract_cost=300,
        style="swing",
        limit=3,
    )
    assert len(candidates) == 1
    assert candidates[0]["contract_type"] == "PUT"
