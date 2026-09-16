from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any, Mapping

import httpx

ROOT = Path(__file__).resolve().parent


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

    signal_enabled = str(env.get("MNT_SIGNAL_DB_ENABLED", "true")).strip().lower() not in {"0", "false", "no", "off"}
    add(
        "signal_history",
        signal_enabled,
        required=False,
        detail="Signal-history calibration enabled." if signal_enabled else "Signal history is disabled; MnT cannot learn from live signals.",
    )

    shadow_enabled = str(env.get("MNT_SHADOW_TRADES_ENABLED", "true")).strip().lower() not in {"0", "false", "no", "off"}
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
    }
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


async def endpoint_checks(base_url: str | None = None) -> list[dict[str, Any]]:
    base_url = (base_url or os.getenv("MNT_DASHBOARD_API_URL", "http://127.0.0.1:8080")).rstrip("/")
    checks = [
        ("dashboard_health", "GET", "/api/health", None, True),
        ("system_bridge", "GET", "/api/system", None, True),
        ("market_radar", "GET", "/api/radar", {"limit": 3}, True),
        ("signal_history_api", "GET", "/api/kronos/signals", {"limit": 1}, False),
    ]
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
    checks = configuration_checks() + storage_checks()
    checks.extend(await endpoint_checks())
    return summarize(checks)


def main() -> None:
    report = asyncio.run(run())
    print(json.dumps(report, indent=2, sort_keys=True))
    raise SystemExit(0 if report["ready"] else 1)


if __name__ == "__main__":
    main()
