from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_opportunity_desk_exposes_trade_levels_and_full_analysis_action():
    js = (ROOT / "static" / "opportunity-desk.js").read_text(encoding="utf-8")

    assert "function buildFastPlan" in js
    assert "Wait for trigger" in js
    assert "Entry zone" in js
    assert "Do not chase above" in js
    assert "Do not chase below" in js
    assert "Stop / invalidation" in js
    assert "Profit target 1" in js
    assert "Profit target 2" in js
    assert "data-mnt-run-analysis=\"true\"" in js
    assert "runFusion" in js


def test_fast_trade_levels_use_real_bars_and_atr_not_current_price_as_entry():
    js = (ROOT / "static" / "opportunity-desk.js").read_text(encoding="utf-8")

    assert "timeframe=5m&limit=80" in js
    assert "atrFromBars" in js
    assert "const trigger = direction === 'LONG' ? Math.max(...highs) : Math.min(...lows);" in js
    assert "const entryLow = trigger - atr * 0.10;" in js
    assert "const entryHigh = trigger + atr * 0.10;" in js
    assert "const noChase" in js
    assert "Full MnT confirmation can cancel or refine these levels." in js


def test_mobile_css_has_trade_plan_layout():
    css = (ROOT / "static" / "opportunity-desk.css").read_text(encoding="utf-8")

    assert ".mnt-trade-plan" in css
    assert ".mnt-plan-grid" in css
    assert "@media (max-width: 430px)" in css
