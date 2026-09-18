from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_dashboard_includes_my_focus_assets_and_workspace_tab():
    html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    assert 'data-mnt-tab="focus"' in html
    assert 'id="mntFocusHost"' in html
    assert '/static/my-focus.css' in html
    assert '/static/my-focus.js' in html


def test_my_focus_ui_supports_watch_stock_and_option_positions():
    js = (ROOT / "static" / "my-focus.js").read_text(encoding="utf-8")
    assert 'WATCHING' in js
    assert 'OPEN_STOCK' in js
    assert 'OPEN_OPTION' in js
    assert '/api/mnt/focus' in js
    assert 'Open + run MnT' in js
    assert "MnTWorkspace?.openTab('trade')" in js


def test_open_option_ui_captures_exact_position_and_live_management():
    js = (ROOT / "static" / "my-focus.js").read_text(encoding="utf-8")
    for field_id in (
        'mntFocusOptionType',
        'mntFocusStrike',
        'mntFocusExpiration',
        'mntFocusQuantity',
    ):
        assert field_id in js
    assert '/option-analysis' in js
    assert 'deep=true' in js
    assert 'MnT POSITION MANAGER' in js
    assert 'Live bid' in js
    assert 'Exit P/L' in js
    assert 'Underlying invalidation' in js
    assert 'recovery_needed_pct' in js


def test_open_stock_ui_captures_shares_and_uses_same_position_manager_pattern():
    js = (ROOT / "static" / "my-focus.js").read_text(encoding="utf-8")
    assert 'mntFocusShares' in js
    assert 'shares:' in js
    assert '/stock-analysis' in js
    assert 'data-focus-analyze-stock' in js
    assert 'MnT STOCK POSITION MANAGER' in js
    assert 'Unrealized P/L' in js
    assert 'Structural invalidation' in js
    assert 'price_checkpoint_10' in js


def test_position_state_changes_can_raise_browser_alerts_when_enabled():
    js = (ROOT / "static" / "my-focus.js").read_text(encoding="utf-8")
    assert 'notifyStateChange' in js
    assert 'Notification.permission' in js
    assert 'mnt:position-state' in js


def test_my_focus_submit_keeps_form_reference_across_await():
    js = (ROOT / "static" / "my-focus.js").read_text(encoding="utf-8")
    assert "const form = event.currentTarget;" in js
    assert "form.reset();" in js
    assert "event.currentTarget.reset();" not in js


def test_my_focus_asset_has_cache_bust_version():
    html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    assert 'my-focus.js?v=20260918-0600' in html
    assert 'my-focus.css?v=20260918-0600' in html
