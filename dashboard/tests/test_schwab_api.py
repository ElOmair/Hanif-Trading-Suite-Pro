from app_schwab import app


def test_schwab_routes_are_mounted_on_dashboard():
    paths = {route.path for route in app.routes}
    assert "/api/schwab/status" in paths
    assert "/api/schwab/authorize" in paths
    assert "/api/schwab/auth-url" in paths
    assert "/api/schwab/callback" in paths
    assert "/api/schwab/positions" in paths
    assert "/api/schwab/quotes" in paths
    assert "/api/schwab/options/{symbol}" in paths
    assert "/api/schwab/options/{symbol}/candidates" in paths


def test_no_schwab_order_route_is_exposed_yet():
    paths = {route.path for route in app.routes}
    assert not any(path.startswith("/api/schwab/orders") for path in paths)
    assert not any(path.startswith("/api/schwab/order") for path in paths)
