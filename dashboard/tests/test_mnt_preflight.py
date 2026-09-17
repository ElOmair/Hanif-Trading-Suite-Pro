from mnt_preflight import configuration_checks, effective_environment, read_env_file, summarize


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


def test_enabled_schwab_requires_keys_secret_and_https_callback():
    checks = configuration_checks(
        {
            "ALPACA_API_KEY": "key",
            "ALPACA_SECRET_KEY": "secret",
            "KRONOS_API_URL": "http://127.0.0.1:8000",
            "MNT_SIGNAL_DB_ENABLED": "true",
            "MNT_SHADOW_TRADES_ENABLED": "true",
            "MNT_SCHWAB_ENABLED": "true",
            "SCHWAB_APP_KEY": "app-key",
            "SCHWAB_APP_SECRET": "app-secret",
            "SCHWAB_CALLBACK_URL": "http://not-secure.example/callback",
        }
    )
    schwab = next(item for item in checks if item["name"] == "schwab_configuration")
    assert schwab["required"] is True
    assert schwab["ok"] is False
    assert summarize(checks)["ready"] is False


def test_enabled_schwab_config_is_ready_with_https_callback():
    checks = configuration_checks(
        {
            "ALPACA_API_KEY": "key",
            "ALPACA_SECRET_KEY": "secret",
            "KRONOS_API_URL": "http://127.0.0.1:8000",
            "MNT_SIGNAL_DB_ENABLED": "true",
            "MNT_SHADOW_TRADES_ENABLED": "true",
            "MNT_SCHWAB_ENABLED": "true",
            "SCHWAB_APP_KEY": "app-key",
            "SCHWAB_APP_SECRET": "app-secret",
            "SCHWAB_CALLBACK_URL": "https://dashboard.example/api/schwab/callback",
        }
    )
    schwab = next(item for item in checks if item["name"] == "schwab_configuration")
    assert schwab["ok"] is True


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


def test_env_file_parser_reads_values_without_shell_execution(tmp_path):
    path = tmp_path / "test.env"
    path.write_text(
        "# comment\nALPACA_API_KEY='abc$123'\nexport ALPACA_SECRET_KEY=secret-value\nBAD LINE\nMNT_PRETRIGGER_SCORE=75\n",
        encoding="utf-8",
    )
    values = read_env_file(path)
    assert values["ALPACA_API_KEY"] == "abc$123"
    assert values["ALPACA_SECRET_KEY"] == "secret-value"
    assert values["MNT_PRETRIGGER_SCORE"] == "75"
    assert "BAD LINE" not in values


def test_effective_environment_matches_systemd_override_order(tmp_path):
    kronos = tmp_path / "kronos.env"
    mnt = tmp_path / "mnt.env"
    kronos.write_text("ALPACA_API_KEY=base-key\nMNT_PRETRIGGER_SCORE=70\n", encoding="utf-8")
    mnt.write_text("MNT_PRETRIGGER_SCORE=76\nMNT_FUSION_SHORTLIST=4\n", encoding="utf-8")
    env = effective_environment(
        {"PROCESS_ONLY": "yes"},
        kronos_env_path=kronos,
        mnt_env_path=mnt,
    )
    assert env["ALPACA_API_KEY"] == "base-key"
    assert env["MNT_PRETRIGGER_SCORE"] == "76"
    assert env["MNT_FUSION_SHORTLIST"] == "4"
    assert env["PROCESS_ONLY"] == "yes"
