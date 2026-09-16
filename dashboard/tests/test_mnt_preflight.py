from mnt_preflight import configuration_checks, summarize


def test_required_alpaca_credentials_fail_preflight_config():
    checks = configuration_checks({"KRONOS_API_URL": "http://127.0.0.1:8000"})
    alpaca = next(item for item in checks if item["name"] == "alpaca_credentials")
    assert alpaca["required"] is True
    assert alpaca["ok"] is False


def test_optional_integrations_warn_but_do_not_block():
    checks = configuration_checks(
        {
            "ALPACA_API_KEY": "key",
            "ALPACA_SECRET_KEY": "secret",
            "KRONOS_API_URL": "http://127.0.0.1:8000",
            "MNT_SIGNAL_DB_ENABLED": "true",
            "MNT_SHADOW_TRADES_ENABLED": "true",
        }
    )
    report = summarize(checks)
    assert report["ready"] is True
    assert report["warnings"] == 2
    assert report["verdict"] == "READY_FOR_SHADOW_SESSION"


def test_required_failure_sets_not_ready():
    report = summarize(
        [
            {"name": "one", "ok": True, "required": True, "detail": "ok"},
            {"name": "two", "ok": False, "required": True, "detail": "bad"},
            {"name": "three", "ok": False, "required": False, "detail": "warn"},
        ]
    )
    assert report["ready"] is False
    assert report["required_failures"] == 1
    assert report["warnings"] == 1
    assert report["verdict"] == "NOT_READY"
