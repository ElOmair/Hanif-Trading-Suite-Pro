from pathlib import Path


STATIC = Path(__file__).resolve().parents[1] / "static"
HTML = STATIC / "broker.html"
SCRIPT = STATIC / "broker.js"


def test_broker_page_has_positions_and_contract_scanner():
    html = HTML.read_text(encoding="utf-8")
    assert "Schwab / thinkorswim Broker Desk" in html
    assert 'id="accounts"' in html
    assert 'id="candidateForm"' in html
    assert "/api/schwab/authorize" in html


def test_broker_browser_code_uses_read_only_endpoints():
    script = SCRIPT.read_text(encoding="utf-8")
    assert "/api/schwab/status" in script
    assert "/api/schwab/positions" in script
    assert "/api/schwab/options/" in script
    assert "candidates" in script
    assert "POST" not in script.upper()
    assert "/orders" not in script


def test_broker_page_explicitly_states_no_order_submission():
    html = HTML.read_text(encoding="utf-8").lower()
    assert "cannot submit, replace, or cancel brokerage orders" in html
    assert "no order routes are exposed" in html
