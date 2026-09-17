from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any, Mapping

import httpx

ROOT = Path(__file__).resolve().parent
DEFAULT_KRONOS_ENV = Path("/home/airomair/Kronos/.env")
DEFAULT_MNT_ENV = ROOT / "mnt.env"


def read_env_file(path: Path) -> dict[str, str]:
    """Parse simple systemd-style KEY=VALUE data without executing it as shell code."""
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key or not all(ch.isalnum() or ch == "_" for ch in key):
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[key] = value
    return values


def effective_environment(
    process_env: Mapping[str, str] | None = None,
    *,
    kronos_env_path: Path = DEFAULT_KRONOS_ENV,
    mnt_env_path: Path = DEFAULT_MNT_ENV,
) -> dict[str, str]:
    """Mirror systemd EnvironmentFile precedence for CLI preflight checks."""
    merged = dict(process_env or os.environ)
    merged.update(read_env_file(kronos_env_path))
    merged.update(read_env_file(mnt_env_path))
    return merged


def _enabled(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    return str(value).strip().lower() not in {"0", "false", "no", "off", ""}


def configuration_checks(env: Mapping[str, str] | None = None) -> list[dict[str, Any]]:
    env = env or os.environ
    checks: list[dict[str, Any]] = []

    def add(name: str, ok: bool, *, required: bool, detail: str) -> None:
        checks.append({"name": name, "ok": bool(ok), "required": required, "detail": detail})

    alpaca_key = str(env.get("ALPACA_API_KEY", "")).strip()
    alpaca_secret = str(env.get("ALPACA_SECRET_KEY", "")).strip()
    add(
        "alpaca_credentials",
        bool(alpaca_key and alpaca_secret),
        required=True,
        detail="Alpaca market-data credentials configured." if alpaca_key and alpaca_secret else "ALPACA_API_KEY/ALPACA_SECRET_KEY are missing.",
    )

    kronos_url = str(env.get("KRONOS_API_URL", "http://127.0.0.1:8000")).strip()
    add("kronos_api_url", bool(kronos_url), required=True, detail=f"Kronos API target: {kronos_url or 'missing'}")

    webhook = str(env.get("MNT_DISCORD_WEBHOOK_URL", "")).strip()
    add(
        "discord_webhook",
        bool(webhook),
        required=False,
        detail="Discord alerts enabled." if webhook else "Discord webhook is not configured; shadow mode can still run.",
    )

    uw = str(env.get("UNUSUAL_WHALES_API_TOKEN", "")).strip()
    add(
        "unusual_whales_token",
        bool(uw),
        required=False,
        detail="Live Gamma/options-flow layers can be enabled." if uw else "No server-side UW token; Gamma/flow coverage will be reweighted out.",
    )

    schwab_enabled = _enabled(env.get("MNT_SCHWAB_ENABLED"), False)
    if schwab_enabled:
        app_key = str(env.get("SCHWAB_APP_KEY", "")).strip()
        app_secret = str(env.get("SCHWAB_APP_SECRET", "")).strip()
        callback = str(env.get("SCHWAB_CALLBACK_URL", "")).strip()
        schwab_ok = bool(app_key and app_secret and callback.startswith("https://"))
        add(
            "schwab_configuration",
            schwab_ok,
            required=True,
            detail=(
                f"Schwab/thinkorswim integration enabled with HTTPS callback {callback}."
                if schwab_ok
                else "MNT_SCHWAB_ENABLED=true requires SCHWAB_APP_KEY, SCHWAB_APP_SECRET, and an HTTPS SCHWAB_CALLBACK_URL."
            ),
        )

    signal_enabled = _enabled(env.get("MNT_SIGNAL_DB_ENABLED"), True)
    add(
        "signal_history",
        signal_enabled,
        required=False,
        detail="Signal-history calibration enabled." if signal_enabled else "Signal history is disabled; MnT cannot learn from live signals.",
    )

    shadow_enabled = _enabled(env.get("MNT_SHADOW_TRADES_ENABLED"), True)
    add(
        "shadow_ready_journal",
        shadow_enabled,
        required=False,
        detail="READY-alert shadow journal enabled." if shadow_enabled else "READY shadow journal disabled.",
    )
    return checks


def storage_checks(env: Mapping[str, str] | None = None) -> list[dict[str, Any]]:
    env = env or os.environ
    targets = {
        "signal_db": Path(str(env.get("MNT_SIGNAL_DB", ROOT / "data" / "mnt_signals.sqlite3"))).expanduser(),
        "shadow_db": Path(str(env.get("MNT_SHADOW_TRADE_DB", ROOT / "data" / "mnt_shadow_trades.sqlite3"))).expanduser(),
        "alert_state": Path(str(env.get("MNT_ALERT_STATE_FILE", ROOT / "data" / "mnt_alert_state.json"))).expanduser(),
        "worker_status": Path(str(env.get("MNT_WORKER_STATUS_FILE", ROOT / "data" / "mnt_worker_status.json"))).expanduser(),
    }
    if _enabled(env.get("MNT_SCHWAB_ENABLED"), False):
        targets["schwab_tokens"] = Path(str(env.get("SCHWAB_TOKEN_FILE", ROOT / "data" / "schwab_tokens.json"))).expanduser()
        targets["schwab_oauth_state"] = Path(str(env.get("SCHWAB_OAUTH_STATE_FILE", ROOT / "data" / "schwab_oauth_state.json"))).expanduser()

    output = []
    for name, path in targets.items():
        parent = path.parent
        try:
            parent.mkdir(parents=True, exist_ok=True)
            probe = parent / ".mnt_preflight_write_test"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
            ok = True
            detail = f"Writable: {parent}"
        except Exception as exc:
            ok = False
            detail = f"Not writable: {parent} ({type(exc).__name__})"
        output.append({"name": name, "ok": ok, "required": True, "detail": detail, "path": str(path)})
    return output


async def endpoint_checks(base_url: str | None = None, *, schwab_required: bool = False) -> list[dict[str, Any]]:
    base_url = (base_url or os.getenv("MNT_DASHBOARD_API_URL", "http://127.0.0.1:8080")).rstrip("/")
    checks = [
        ("dashboard_health", "GET", "/api/health", None, True),
        ("system_bridge", "GET", "/api/system", None, True),
        ("market_radar", "GET", "/api/radar", {"limit": 3}, True),
        ("signal_history_api", "GET", "/api/kronos/signals", {"limit": 1}, False),
    ]
    if schwab_required:
        checks.append(("schwab_authorization", "GET", "/api/schwab/status", None, True))

    results = []
    async with httpx.AsyncClient(timeout=12.0) as client:
        for name, method, path, params, required in checks:
            try:
                response = await client.request(method, f"{base_url}{path}", params=params)
                ok = response.is_success
                detail = f"HTTP {response.status_code} from {path}"
                if name == "system_bridge" and ok:
                    try:
                        body = response.json()
                        kronos_online = bool((body.get("kronos") or {}).get("online"))
                        ok = ok and kronos_online
                        if not kronos_online:
                            detail += "; Kronos backend reports offline"
                    except Exception:
                        ok = False
                        detail += "; invalid JSON response"
                elif name == "schwab_authorization" and ok:
                    try:
                        body = response.json()
                        authorized = bool(body.get("authorized"))
                        refresh_valid = bool(body.get("refresh_token_valid"))
                        ok = authorized and refresh_valid
                        if ok:
                            detail += "; Schwab OAuth refresh token is valid"
                        else:
                            detail += "; interactive Schwab authorization is still required"
                    except Exception:
                        ok = False
                        detail += "; invalid JSON response"
                results.append({"name": name, "ok": ok, "required": required, "detail": detail})
            except Exception as exc:
                results.append(
                    {
                        "name": name,
                        "ok": False,
                        "required": required,
                        "detail": f"{path} unavailable ({type(exc).__name__})",
                    }
                )
    return results


def summarize(checks: list[dict[str, Any]]) -> dict[str, Any]:
    required_failures = [item for item in checks if item.get("required") and not item.get("ok")]
    warnings = [item for item in checks if not item.get("required") and not item.get("ok")]
    return {
        "ready": not required_failures,
        "required_failures": len(required_failures),
        "warnings": len(warnings),
        "checks": checks,
        "verdict": "READY_FOR_SHADOW_SESSION" if not required_failures else "NOT_READY",
        "note": "Preflight validates service/configuration readiness only; it does not validate profitability or authorize orders.",
    }


async def run() -> dict[str, Any]:
    env = effective_environment()
    base_url = str(env.get("MNT_DASHBOARD_API_URL", "http://127.0.0.1:8080"))
    schwab_required = _enabled(env.get("MNT_SCHWAB_ENABLED"), False)
    checks = configuration_checks(env) + storage_checks(env)
    checks.extend(await endpoint_checks(base_url, schwab_required=schwab_required))
    return summarize(checks)


def main() -> None:
    report = asyncio.run(run())
    print(json.dumps(report, indent=2, sort_keys=True))
    raise SystemExit(0 if report["ready"] else 1)


if __name__ == "__main__":
    main()
