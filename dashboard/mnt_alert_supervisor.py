from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

import httpx

from daily_scorecard_alert import maybe_send_daily_scorecard
from focused_alert_scan import scan_once
from learning_snapshot import write_learning_snapshot
from mnt_alert_worker import AlertState, _env_float, market_scan_active
from option_shadow_collector import refresh_due_option_marks
from position_state_alerts import PositionAlertState, refresh_position_alerts
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
    position_state_path = Path(
        os.getenv(
            "MNT_POSITION_ALERT_STATE_FILE",
            str(Path(__file__).resolve().parent / "data" / "mnt_position_alert_state.json"),
        )
    )
    position_state = PositionAlertState(position_state_path)

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

                    # Managed positions are monitored independently of fresh-entry
                    # alert gating. The first observation only establishes a baseline;
                    # Discord is used when a position's management state changes.
                    try:
                        position_alerts = await refresh_position_alerts(client, position_state)
                        results.append({"stage": "position_alerts", **position_alerts})
                    except Exception as position_exc:
                        results.append(
                            {
                                "stage": "position_alerts",
                                "status": "error",
                                "checked": 0,
                                "sent": 0,
                                "error": type(position_exc).__name__,
                            }
                        )

                # This is evaluated on every supervisor loop, including after-hours,
                # so a scorecard configured for 16:15 ET is not dependent on the
                # intraday scanner still being active. State prevents duplicate sends.
                try:
                    scorecard_delivery = await maybe_send_daily_scorecard(client)
                    results.append({"stage": "daily_scorecard", **scorecard_delivery})
                except Exception as scorecard_exc:
                    results.append(
                        {
                            "stage": "daily_scorecard",
                            "status": "error",
                            "sent": False,
                            "error": type(scorecard_exc).__name__,
                        }
                    )

                if active or any(item.get("stage") == "daily_scorecard" and item.get("sent") for item in results):
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
                    # Publish only aggregate research metrics to the browser. The
                    # snapshot intentionally excludes env values, credentials and
                    # raw signal payloads.
                    write_learning_snapshot(status)
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
