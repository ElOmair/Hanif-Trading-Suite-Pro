import asyncio

import app as dashboard


def test_tick_prefers_schwab_when_ready(monkeypatch):
    dashboard._tick_cache.clear()
    monkeypatch.setattr(dashboard, "MARKET_DATA_PRIMARY", "schwab")
    monkeypatch.setattr(dashboard, "schwab_market_ready", lambda: True)

    async def fake_schwab(symbol):
        return {"symbol": symbol, "provider": "schwab", "quote": {"mid": 500.25}}

    async def fail_alpaca(symbol):
        raise AssertionError("Alpaca fallback should not be used")

    monkeypatch.setattr(dashboard, "schwab_latest_quote", fake_schwab)
    monkeypatch.setattr(dashboard, "_alpaca_tick_payload", fail_alpaca)
    result = asyncio.run(dashboard._get_tick_payload("SPY"))
    assert result["provider"] == "schwab"
    assert result["fallback"] is False
    assert result["quote"]["mid"] == 500.25


def test_tick_falls_back_to_alpaca_when_schwab_fails(monkeypatch):
    dashboard._tick_cache.clear()
    monkeypatch.setattr(dashboard, "MARKET_DATA_PRIMARY", "schwab")
    monkeypatch.setattr(dashboard, "schwab_market_ready", lambda: True)

    async def fail_schwab(symbol):
        raise RuntimeError("temporary Schwab outage")

    async def fake_alpaca(symbol):
        return {"symbol": symbol, "provider": "alpaca_iex", "quote": {"mid": 499.90}}

    monkeypatch.setattr(dashboard, "schwab_latest_quote", fail_schwab)
    monkeypatch.setattr(dashboard, "_alpaca_tick_payload", fake_alpaca)
    result = asyncio.run(dashboard._get_tick_payload("SPY"))
    assert result["provider"] == "alpaca_iex"
    assert result["fallback"] is True
    assert result["provider_errors"]["schwab"] == "RuntimeError"


def test_bars_prefers_schwab(monkeypatch):
    dashboard._bars_cache.clear()
    monkeypatch.setattr(dashboard, "MARKET_DATA_PRIMARY", "schwab")
    monkeypatch.setattr(dashboard, "schwab_market_ready", lambda: True)

    async def fake_schwab(symbol, timeframe, limit):
        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "provider": "schwab",
            "bars": [
                {"time": 1_700_000_000 + i * 300, "open": 10, "high": 11, "low": 9, "close": 10.5, "volume": 1000}
                for i in range(50)
            ],
        }

    async def fail_alpaca(symbol, timeframe, limit):
        raise AssertionError("Alpaca fallback should not be used")

    monkeypatch.setattr(dashboard, "schwab_bars", fake_schwab)
    monkeypatch.setattr(dashboard, "_alpaca_bars_payload", fail_alpaca)
    result = asyncio.run(dashboard.bars("SPY", "5m", 50))
    assert result["provider"] == "schwab"
    assert result["fallback"] is False
    assert len(result["bars"]) == 50
