import schwab_api
from app_schwab import app
from fastapi.testclient import TestClient


def _router_paths():
    return {getattr(route, "path", "") for route in schwab_api.router.routes}


def test_schwab_routes_are_mounted_on_dashboard(monkeypatch):
    monkeypatch.setattr(
        schwab_api,
        "token_status",
        lambda: {"configured": False, "authorized": False},
    )
    response = TestClient(app).get("/api/schwab/status")
    assert response.status_code == 200
    assert response.json()["phase"] == "READ_ONLY_PHASE_1"

    paths = _router_paths()
    assert "/api/schwab/status" in paths
    assert "/api/schwab/authorize" in paths
    assert "/api/schwab/auth-url" in paths
    assert "/api/schwab/callback" in paths
    assert "/api/schwab/positions" in paths
    assert "/api/schwab/quotes" in paths
    assert "/api/schwab/options/{symbol}" in paths
    assert "/api/schwab/options/{symbol}/candidates" in paths


def test_no_schwab_order_route_is_exposed_yet():
    paths = _router_paths()
    assert not any(path.startswith("/api/schwab/orders") for path in paths)
    assert not any(path.startswith("/api/schwab/order") for path in paths)


def test_phase1_status_forces_order_submission_disabled(monkeypatch):
    monkeypatch.setattr(
        schwab_api,
        "token_status",
        lambda: {"configured": True, "authorized": True, "order_submission_enabled": True},
    )
    payload = schwab_api.status()
    assert payload["order_submission_enabled"] is False
    assert payload["phase"] == "READ_ONLY_PHASE_1"
    assert payload["research_only"] is True
