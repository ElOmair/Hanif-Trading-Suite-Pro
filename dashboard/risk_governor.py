from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any


def _number(value: Any) -> float | None:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if value == value else None


def _env_float(name: str, default: float, minimum: float = 0.0) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(minimum, value)


def _decision_label(decision: Any) -> str:
    if isinstance(decision, dict):
        for key in ("decision", "action", "state", "status"):
            value = decision.get(key)
            if value:
                return str(value).upper()
    return str(decision or "UNKNOWN").upper()


def _no_chase(
    technical: dict[str, Any],
    trade_plan: dict[str, Any] | None,
) -> dict[str, Any]:
    plan = trade_plan or {}
    direction = str(technical.get("signal") or technical.get("direction") or "").upper()
    price = _number(technical.get("price"))
    atr = _number(technical.get("atr"))
    entry_low = _number(plan.get("entry_low") or plan.get("entryLow") or technical.get("entry_low"))
    entry_high = _number(plan.get("entry_high") or plan.get("entryHigh") or technical.get("entry_high"))
    limit = _number(plan.get("no_chase") or plan.get("no_chase_price") or plan.get("chase_limit") or plan.get("chaseLimit"))
    atr_buffer = _env_float("MNT_NO_CHASE_ATR", 0.25, 0.0)

    if limit is None and atr is not None:
        if direction == "LONG" and entry_high is not None:
            limit = entry_high + atr * atr_buffer
        elif direction == "SHORT" and entry_low is not None:
            limit = entry_low - atr * atr_buffer

    blocked = False
    if price is not None and limit is not None:
        if direction == "LONG":
            blocked = price > limit
        elif direction == "SHORT":
            blocked = price < limit

    return {
        "direction": direction,
        "price": price,
        "entry_low": entry_low,
        "entry_high": entry_high,
        "limit": round(limit, 6) if limit is not None else None,
        "blocked": blocked,
        "atr_buffer": atr_buffer,
    }


def build_execution_gate(
    *,
    technical: dict[str, Any] | None,
    fusion_score: dict[str, Any] | None,
    decision: Any,
    trade_plan: dict[str, Any] | None = None,
    market_gate: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Build the server-side gate for reviewing an entry.

    This does not authorize or place an order. It makes stale/low-quality/chased
    setup states explicit so clients cannot accidentally treat a raw CONFIRM as
    sufficient when MnT's broader checks disagree.
    """
    technical = technical or {}
    fusion_score = fusion_score or {}
    market_gate = market_gate or {}
    direction = str(technical.get("signal") or technical.get("direction") or "NEUTRAL").upper()
    score = _number(fusion_score.get("score"))
    coverage = _number(fusion_score.get("coverage_pct"))
    min_score = _env_float("MNT_MIN_REVIEW_SCORE", 62.0, 0.0)
    min_coverage = _env_float("MNT_MIN_REVIEW_COVERAGE", 55.0, 0.0)
    ttl_minutes = _env_float("MNT_SETUP_TTL_MINUTES", 10.0, 1.0)
    generated_at = now or datetime.now(timezone.utc)
    if generated_at.tzinfo is None:
        generated_at = generated_at.replace(tzinfo=timezone.utc)
    else:
        generated_at = generated_at.astimezone(timezone.utc)
    expires_at = generated_at + timedelta(minutes=ttl_minutes)
    decision_label = _decision_label(decision)
    chase = _no_chase(technical, trade_plan)

    blockers: list[dict[str, str]] = []
    waits: list[dict[str, str]] = []

    if market_gate.get("active"):
        blockers.append({"code": "OPENING_LOCKOUT", "reason": str(market_gate.get("reason") or "Opening lockout is active.")})
    if direction not in {"LONG", "SHORT"}:
        blockers.append({"code": "NO_DIRECTION", "reason": "The short-term signal is neutral or missing."})
    if coverage is None or coverage < min_coverage:
        blockers.append({"code": "LOW_COVERAGE", "reason": f"Data coverage must be at least {min_coverage:.0f}% before entry review."})
    if score is None or score < min_score:
        blockers.append({"code": "LOW_SCORE", "reason": f"MnT score must be at least {min_score:.0f}/100 before entry review."})
    if chase.get("blocked"):
        blockers.append({"code": "NO_CHASE", "reason": "Price has moved beyond the current no-chase limit. Re-analyze or wait for a retest."})

    if "REJECT" in decision_label:
        blockers.append({"code": "DECISION_REJECT", "reason": "The Decision Engine rejected the setup."})
    elif "CONFIRM" not in decision_label:
        waits.append({"code": "AWAIT_CONFIRMATION", "reason": "The Decision Engine has not confirmed the setup yet."})

    review_allowed = not blockers and not waits
    state = "REVIEW_ENTRY" if review_allowed else "BLOCKED" if blockers else "WAIT"
    primary_reason = (
        "All current MnT review gates passed. Re-check before acting if price changes materially."
        if review_allowed
        else (blockers[0]["reason"] if blockers else waits[0]["reason"])
    )

    return {
        "state": state,
        "entry_review_allowed": review_allowed,
        "order_authorized": False,
        "research_only": True,
        "direction": direction,
        "score": score,
        "coverage_pct": coverage,
        "decision": decision_label,
        "primary_reason": primary_reason,
        "blockers": blockers,
        "wait_conditions": waits,
        "no_chase": chase,
        "generated_at": generated_at.isoformat(),
        "expires_at": expires_at.isoformat(),
        "ttl_minutes": ttl_minutes,
        "requirements": {
            "min_score": min_score,
            "min_coverage_pct": min_coverage,
            "no_chase_atr_buffer": chase.get("atr_buffer"),
        },
        "note": "This gate controls setup review only. It does not place or authorize a brokerage order.",
    }
