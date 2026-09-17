from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

import httpx

from mnt_alert_worker import AlertState, _env_float, market_scan_active, scan_once
from option_shadow_collector import refresh_due_option_marks
from session_risk import session_risk_status
from worker_health import build_worker_status, write_worker_status


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def run_forever() -> None:
    interval = _env_float("MNT_ALERT_SCAN_SECONDS", 60.0, 30.0)
    import os

    state_path = Path(
        os.getenv(
            "MNT_ALERT_STATE_FILE",
            str(Path(__file__).resolve().parent / "data" / "mnt_alert_state.json"),
        )
    )
    state = AlertState(state_path)

    async with httpx.AsyncClient(timeout=20.0) as client:
        while True:
            active = market_scan_active()
            started = _iso_now()
            results = []
            loop_error = None
            try:
                risk = session_risk_status()
                results.append({"stage": "session_risk", **risk})
                if active:
                    if not risk.get("entry_review_blocked"):
                        results.extend(await scan_once(client, state))
                    else:
                        results.append(
                            {
                                "stage": "scanner_pause",
                                "reason": "session_risk_governor",
                                "beginner_explanation": risk.get("beginner_explanation"),
                            }
                        )
                    # Existing READY shadow trades keep receiving option marks even
                    # when new alert delivery is paused by the optional risk governor.
                    option_marks = await refresh_due_option_marks(client)
                    results.append({"stage": "option_marks", **option_marks})
                    print(
                        json.dumps(
                            {"time": _iso_now(), "results": results},
                            separators=(",", ":"),
                        ),
                        flush=True,
                    )
            except Exception as exc:
                loop_error = f"{type(exc).__name__}: {exc}"
                print(
                    json.dumps(
                        {"time": _iso_now(), "worker_error": loop_error},
                        separators=(",", ":"),
                    ),
                    flush=True,
                )
            finally:
                try:
                    status = build_worker_status(
                        results,
                        market_active=active,
                        scan_started_at=started,
                        scan_finished_at=_iso_now(),
                        loop_error=loop_error,
                    )
                    write_worker_status(status)
                except Exception as health_exc:
                    print(
                        json.dumps(
                            {
                                "time": _iso_now(),
                                "heartbeat_error": type(health_exc).__name__,
                            },
                            separators=(",", ":"),
                        ),
                        flush=True,
                    )

            await asyncio.sleep(interval)


if __name__ == "__main__":
    asyncio.run(run_forever())
