import asyncio
from urllib.parse import parse_qs, urlparse

import schwab_provider as schwab


def _configure(monkeypatch, tmp_path):
    monkeypatch.setenv("MNT_SCHWAB_ENABLED", "true")
    monkeypatch.setenv("SCHWAB_APP_KEY", "test-app-key")
    monkeypatch.setenv("SCHWAB_APP_SECRET", "super-secret")
    monkeypatch.setenv("SCHWAB_CALLBACK_URL", "https://dashboard.example/api/schwab/callback")
    monkeypatch.setenv("SCHWAB_TOKEN_FILE", str(tmp_path / "tokens.json"))
    monkeypatch.setenv("SCHWAB_OAUTH_STATE_FILE", str(tmp_path / "state.json"))
    monkeypatch.delenv("MNT_SCHWAB_ORDER_SUBMISSION_ENABLED", raising=False)


def test_auth_url_contains_state_but_never_client_secret(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path)
    url = schwab.begin_oauth()
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    assert query["client_id"] == ["test-app-key"]
    assert query["redirect_uri"] == ["https://dashboard.example/api/schwab/callback"]
    assert query["state"][0]
    assert "super-secret" not in url
    assert (tmp_path / "state.json").exists()


def test_token_status_never_exposes_token_values(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path)
    schwab._write_private_json(
        tmp_path / "tokens.json",
        {
            "access_token": "access-secret",
            "refresh_token": "refresh-secret",
            "access_expires_at": schwab._epoch_now() + 900,
            "refresh_expires_at": schwab._epoch_now() + 86400,
        },
    )
    status = schwab.token_status()
    encoded = str(status)
    assert status["authorized"] is True
    assert status["refresh_token_valid"] is True
    assert status["order_submission_enabled"] is False
    assert "access-secret" not in encoded
    assert "refresh-secret" not in encoded


def test_positions_mask_account_numbers_and_hashes(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path)

    async def fake_map():
        return [{"accountNumber": "123456789", "hashValue": "private-hash"}]

    async def fake_get(path, *, market_data=False, params=None):
        assert path == "/accounts/private-hash"
        assert params == {"fields": "positions"}
        return {
            "securitiesAccount": {
                "type": "MARGIN",
                "currentBalances": {"liquidationValue": 2500.0, "buyingPower": 4000.0},
                "positions": [
                    {
                        "longQuantity": 1,
                        "shortQuantity": 0,
                        "averagePrice": 2.25,
                        "marketValue": 260.0,
                        "currentDayProfitLoss": 35.0,
                        "currentDayProfitLossPercentage": 15.56,
                        "instrument": {"symbol": "SPY  261016C00760000", "assetType": "OPTION"},
                    }
                ],
            }
        }

    monkeypatch.setattr(schwab, "account_number_map", fake_map)
    monkeypatch.setattr(schwab, "api_get", fake_get)
    result = asyncio.run(schwab.positions())
    encoded = str(result)
    assert result["accounts"][0]["account"] == "••••6789"
    assert result["accounts"][0]["positions"][0]["asset_type"] == "OPTION"
    assert "123456789" not in encoded
    assert "private-hash" not in encoded
    assert result["read_only"] is True


def test_disabled_integration_reports_not_configured(monkeypatch):
    monkeypatch.setenv("MNT_SCHWAB_ENABLED", "false")
    assert schwab.configured() is False
    assert schwab.token_status()["configured"] is False
