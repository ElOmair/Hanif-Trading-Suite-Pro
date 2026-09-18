from pathlib import Path


STATIC = Path(__file__).resolve().parents[1] / "static"
INDEX = STATIC / "index.html"
SCRIPT = STATIC / "learning-lab.js"
STYLE = STATIC / "learning-lab.css"


def test_learning_lab_assets_are_wired_into_dashboard():
    html = INDEX.read_text(encoding="utf-8")
    assert 'id="mntLearningLab"' in html
    assert "/static/learning-lab.css" in html
    assert "/static/learning-lab.js" in html


def test_learning_lab_reads_only_browser_safe_runtime_snapshot():
    script = SCRIPT.read_text(encoding="utf-8")
    assert 'SNAPSHOT_URL = "/static/mnt-runtime.json"' in script
    assert "ALPACA_API_KEY" not in script
    assert "ALPACA_SECRET_KEY" not in script
    assert "MNT_DISCORD_WEBHOOK_URL" not in script


def test_learning_lab_surfaces_shadow_option_horizons_risk_and_learning_policy():
    script = SCRIPT.read_text(encoding="utf-8")
    for horizon in (15, 30, 60, 120):
        assert str(horizon) in script
    assert "option_contract_returns" in script
    assert "session_risk" in script
    assert "weight_challenge" in script
    assert "daily_scorecard" in script
    assert "edge_slices" in script
    assert "Measured edge" in script
    assert "NO CLEAR SLICE" in script
    assert "SUPPORTED" in script
    assert "KEEP CURRENT" in script
    assert "Today's quality" in script
    assert "shadow" in script.lower()


def test_learning_lab_style_supports_mobile_layout():
    css = STYLE.read_text(encoding="utf-8")
    assert ".mnt-learning-grid" in css
    assert ".mnt-horizon-grid" in css
    assert "@media (max-width: 620px)" in css
