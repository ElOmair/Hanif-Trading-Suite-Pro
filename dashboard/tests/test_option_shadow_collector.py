import json

import httpx
import pytest

import option_shadow_collector as collector


def test_parse_latest_quotes_normalizes_alpaca_payload():
    payload = {
        "quotes": {
            "SPY260918C00760000": {"bp": 2.1, "ap": 2.2, "t": "2026-09-16T15:00:00Z"}
        }
    }
    quotes = collector.parse_latest_quotes(payload)
    assert quotes["SPY260918C00760000"]["bid"] == 2.1
    assert quotes["SPY260918C00760000"]["ask"] == 2.2


@pytest.mark.asyncio
async def test_fetch_latest_quotes_falls_back_to_indicative_on_403():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        feed = request.url.params.get("feed")
        if feed == "opra":
            return httpx.Response(403, request=request, json={"message": "forbidden"})
        return httpx.Response(
            200,
            request=request,
            json={
                "quotes": {
                    "SPY260918C00760000": {
                        "bp": 2.0,
                        "ap": 2.1,
                        "t": "2026-09-16T15:00:00Z",
                    }
                }
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        quotes, feed = await collector.fetch_latest_option_quotes(
            client,
            ["SPY260918C00760000"],
            api_key="key",
            secret_key="secret",
            feed="opra",
        )

    assert feed == "indicative"
    assert quotes["SPY260918C00760000"]["bid"] == 2.0
    assert len(calls) == 2
    assert "feed=opra" in calls[0]
    assert "feed=indicative" in calls[1]


@pytest.mark.asyncio
async def test_refresh_due_marks_reuses_one_quote_for_multiple_horizons(monkeypatch):
    due = [
        {
            "shadow_trade_id": 1,
            "signal_id": 10,
            "option_symbol": "SPY260918C00760000",
            "entry_ask": 2.0,
            "horizon_minutes": 15,
            "actual_age_minutes": 31.0,
            "lag_minutes": 16.0,
        },
        {
            "shadow_trade_id": 1,
            "signal_id": 10,
            "option_symbol": "SPY260918C00760000",
            "entry_ask": 2.0,
            "horizon_minutes": 30,
            "actual_age_minutes": 31.0,
            "lag_minutes": 1.0,
        },
    ]
    recorded = []

    monkeypatch.setenv("ALPACA_API_KEY", "key")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "secret")
    monkeypatch.setattr(collector, "due_option_marks", lambda: due)

    async def fake_fetch(client, symbols, **kwargs):
        assert list(symbols) == ["SPY260918C00760000"]
        return {"SPY260918C00760000": {"bid": 2.4, "ask": 2.5}}, "indicative"

    def fake_record(item, quote, *, feed=None):
        recorded.append((item["horizon_minutes"], quote["bid"], feed))
        return len(recorded)

    monkeypatch.setattr(collector, "fetch_latest_option_quotes", fake_fetch)
    monkeypatch.setattr(collector, "record_option_mark", fake_record)

    async with httpx.AsyncClient() as client:
        result = await collector.refresh_due_option_marks(client)

    assert result["marks_recorded"] == 2
    assert result["quoted_contracts"] == 1
    assert recorded == [(15, 2.4, "indicative"), (30, 2.4, "indicative")]
