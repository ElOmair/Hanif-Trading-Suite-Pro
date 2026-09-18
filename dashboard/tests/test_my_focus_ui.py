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
    assert 'runFusion' in js
    assert "MnTWorkspace?.openTab('trade')" in js


def test_my_focus_submit_keeps_form_reference_across_await():
    js = (ROOT / "static" / "my-focus.js").read_text(encoding="utf-8")
    assert "const form = event.currentTarget;" in js
    assert "form.reset();" in js
    assert "event.currentTarget.reset();" not in js


def test_my_focus_asset_has_cache_bust_version():
    html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    assert 'my-focus.js?v=20260918-0130' in html
