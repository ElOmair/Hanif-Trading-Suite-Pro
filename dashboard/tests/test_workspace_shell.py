from pathlib import Path


STATIC = Path(__file__).resolve().parents[1] / "static"


def test_workspace_keeps_symbol_search_quote_and_health_at_top():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    header_start = html.index('<header class="topbar mnt-command-bar">')
    header_end = html.index('</header>', header_start)
    header = html[header_start:header_end]
    assert 'id="symbolForm"' in header
    assert 'id="symbolInput"' in header
    assert 'id="activeSymbol"' in header
    assert 'id="lastPrice"' in header
    assert 'id="kronosStatus"' in header
    assert 'data-mnt-analyze-current' in header


def test_workspace_separates_major_jobs_into_single_purpose_tabs():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert html.count('data-mnt-panel=') == 6
    assert 'id="longRadar"' in html
    assert 'id="mntFocusHost"' in html
    assert 'id="mntOpportunityHost"' in html
    assert 'class="panel positions-card"' in html
    assert 'id="mntLearningLab"' in html


def test_workspace_navigation_handles_cross_tab_trade_actions_and_mobile():
    js = (STATIC / "workspace-tabs.js").read_text(encoding="utf-8")
    css = (STATIC / "workspace-shell.css").read_text(encoding="utf-8")
    assert "openTab('trade')" in js
    assert ".radar-row, [data-mnt-symbol], [data-underlying]" in js
    assert "MutationObserver" in js
    assert "Alt+1" not in js  # keyboard mapping is code-driven, not hardcoded display text
    assert "@media (max-width: 700px)" in css
    assert "overflow-x: auto" in css


def test_trade_panel_is_initially_visible_for_chart_startup_dimensions():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert 'class="mnt-workspace-panel is-active" data-mnt-panel="trade"' in html
    js = (STATIC / "workspace-tabs.js").read_text(encoding="utf-8")
    assert "Lightweight Charts gets real startup dimensions" in js
