import asyncio
from pathlib import Path

import schwab_api


STATIC = Path(__file__).resolve().parents[1] / "static"


def test_main_dashboard_wires_unified_navigation_and_broker_modules():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert "Home" in html
    assert "Trades" in html
    assert "Invest / Holds" in html
    assert "Portfolio" in html
    assert "Learning" in html
    assert 'href="/broker"' in html
    assert "/static/unified-shell.css" in html
    assert "/static/portfolio-panel.js" in html
    assert "/static/schwab-fusion.js" in html
    assert "/static/portfolio-coach.js" in html
    assert "/static/fundamental-holds.js" in html


def test_broker_page_links_back_to_same_unified_app():
    html = (STATIC / "broker.html").read_text(encoding="utf-8")
    assert 'href="/"' in html
    assert 'href="/#trades"' in html
    assert 'href="/#mntOpportunityShell"' in html
    assert 'href="/#mntLearningLab"' in html
    assert "Order submission" in html
    assert "DISABLED" in html


def test_position_aware_frontend_has_no_order_submission_calls():
    combined = "\n".join(
        (STATIC / name).read_text(encoding="utf-8")
        for name in ("portfolio-panel.js", "portfolio-coach.js", "schwab-fusion.js", "fundamental-holds.js")
    )
    assert "/api/schwab/portfolio/" in combined
    assert "/api/schwab/options/" in combined
    assert "/api/schwab/fundamentals/" in combined
    assert "/api/schwab/orders" not in combined
    assert "placeOrder" not in combined


def test_fundamental_snapshot_endpoint_uses_schwab_quote_data(monkeypatch):
    async def fake_quotes(symbols):
        assert symbols == ["NVDA"]
        return {
            "NVDA": {
                "fundamental": {"eps": 4.0, "peRatio": 25.0, "avg10DaysVolume": 20, "avg1YearVolume": 10},
                "quote": {"lastPrice": 180, "52WeekHigh": 200, "52WeekLow": 100},
            }
        }

    monkeypatch.setattr(schwab_api, "quotes", fake_quotes)
    result = asyncio.run(schwab_api.fundamental_snapshot("nvda"))
    assert result["symbol"] == "NVDA"
    assert result["provider"] == "schwab"
    assert result["research_only"] is True
    assert result["score"] is not None
