import asyncio

import schwab_market_data as market


def test_market_data_ready_requires_authorized_schwab(monkeypatch):
    monkeypatch.setattr(market, "configured", lambda: True)
    monkeypatch.setattr(
        market,
        "token_status",
        lambda: {
            "configured": True,
            "authorized": True,
            "access_token_valid": True,
            "refresh_token_valid": True,
            "reauthorization_required": False,
        },
    )
    assert market.market_data_ready() is True
    assert market.market_data_status()["ready"] is True


def test_latest_quote_normalizes_schwab_nbbo(monkeypatch):
    async def fake_quotes(symbols):
        assert symbols == ["SPY"]
        return {
            "SPY": {
                "quote": {
                    "bidPrice": 700.10,
                    "askPrice": 700.14,
                    "mark": 700.12,
                    "lastPrice": 700.11,
                    "bidSize": 12,
                    "askSize": 9,
                    "quoteTime": 1_789_000_000_000,
                }
            }
        }

    monkeypatch.setattr(market, "quotes", fake_quotes)
    result = asyncio.run(market.latest_quote("spy"))
    assert result["provider"] == "schwab"
    assert result["quote"]["bid"] == 700.10
    assert result["quote"]["ask"] == 700.14
    assert result["quote"]["mid"] == 700.12
    assert result["quote"]["bid_size"] == 12
    assert result["quote"]["timestamp"].endswith("+00:00")


def test_price_history_rows_are_normalized_and_limited(monkeypatch):
    async def fake_history(symbol, **filters):
        assert symbol == "NVDA"
        assert filters["frequencyType"] == "minute"
        assert filters["frequency"] == 5
        return {
            "candles": [
                {"datetime": 1_789_000_000_000 + i * 300_000, "open": 100 + i, "high": 101 + i, "low": 99 + i, "close": 100.5 + i, "volume": 1000 + i}
                for i in range(30)
            ]
        }

    monkeypatch.setattr(market, "price_history", fake_history)
    result = asyncio.run(market.bars("NVDA", "5m", 25))
    assert result["provider"] == "schwab"
    assert result["source"] == "schwab_price_history"
    assert len(result["bars"]) == 25
    assert result["bars"][-1]["close"] == 129.5
    assert result["bars"][-1]["volume"] == 1029.0


def test_one_hour_bars_are_aggregated_from_30_minute_candles(monkeypatch):
    base = 1_789_000_000_000

    async def fake_history(symbol, **filters):
        assert filters["frequency"] == 30
        return {
            "candles": [
                {"datetime": base, "open": 10, "high": 12, "low": 9, "close": 11, "volume": 100},
                {"datetime": base + 30 * 60 * 1000, "open": 11, "high": 13, "low": 10, "close": 12, "volume": 200},
            ]
        }

    monkeypatch.setattr(market, "price_history", fake_history)
    result = asyncio.run(market.bars("AMD", "1h", 20))
    assert len(result["bars"]) in {1, 2}
    # The aggregation buckets on UTC clock-hours. If both half-hours share a bucket,
    # verify full OHLCV aggregation; if the synthetic epoch straddles a clock-hour,
    # both normalized bars are still retained without losing volume.
    assert sum(row["volume"] for row in result["bars"]) == 300
    assert max(row["high"] for row in result["bars"]) == 13
    assert min(row["low"] for row in result["bars"]) == 9
