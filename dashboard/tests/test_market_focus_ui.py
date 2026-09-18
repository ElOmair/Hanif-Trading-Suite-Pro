from pathlib import Path

import app_schwab


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"


def test_market_focus_route_is_mounted():
    paths = {getattr(route, "path", None) for route in app_schwab.app.routes}
    assert "/api/market/focus" in paths


def test_market_workspace_mounts_focus_mode_assets():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert 'id="mntMarketFocusHost"' in html
    assert "/static/market-focus.css?v=" in html
    assert "/static/market-focus.js?v=" in html
    assert "Focus Mode is what drives the unattended Kronos shortlist" in html


def test_market_focus_js_links_movers_to_trade_desk():
    script = (STATIC / "market-focus.js").read_text(encoding="utf-8")
    assert "/api/market/focus" in script
    assert "MnTWorkspace?.openTab('trade')" in script
    assert "runFusion" in script
