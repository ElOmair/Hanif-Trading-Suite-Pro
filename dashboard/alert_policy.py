from __future__ import annotations

from typing import Any


def _number(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed == parsed else None


def _decision_label(value: Any) -> str:
    if isinstance(value, dict):
        for key in ("decision", "action", "state", "status"):
            if value.get(key):
                return str(value[key]).upper()
    return str(value or "UNKNOWN").upper()


def classify_alert(
    payload: dict[str, Any],
    *,
    pretrigger_score: float = 72.0,
    pretrigger_coverage: float = 55.0,
) -> dict[str, Any]:
    """Classify one Fusion payload into a Discord alert state.

    READY means the server-side execution gate allows entry review. PRE_TRIGGER is
    intentionally earlier: quality is building, but confirmation is not complete.
    This prevents Discord from first speaking after the trigger has already passed.
    """
    fusion = payload.get("fusion_score") or {}
    gate = payload.get("execution_gate") or {}
    technical = payload.get("technical") or {}
    market_gate = payload.get("market_gate") or {}

    symbol = str(payload.get("symbol") or "").upper()
    direction = str(fusion.get("direction") or technical.get("signal") or "NEUTRAL").upper()
    score = _number(fusion.get("score"))
    coverage = _number(fusion.get("coverage_pct"))
    decision = _decision_label(payload.get("decision"))
    gate_state = str(gate.get("state") or "").upper()

    if market_gate.get("active"):
        return {"alert": False, "state": "OPENING_LOCKOUT", "symbol": symbol, "direction": direction}
    if direction not in {"LONG", "SHORT"}:
        return {"alert": False, "state": "NO_DIRECTION", "symbol": symbol, "direction": direction}
    if "REJECT" in decision:
        return {"alert": False, "state": "REJECTED", "symbol": symbol, "direction": direction}

    if gate.get("entry_review_allowed") is True or gate_state == "REVIEW_ENTRY":
        return {
            "alert": True,
            "state": "READY",
            "priority": 3,
            "symbol": symbol,
            "direction": direction,
            "score": score,
            "coverage_pct": coverage,
            "decision": decision,
            "reason": str(gate.get("primary_reason") or "All current review gates passed."),
        }

    no_chase = gate.get("no_chase") or {}
    if no_chase.get("blocked"):
        return {
            "alert": False,
            "state": "NO_CHASE",
            "symbol": symbol,
            "direction": direction,
            "score": score,
            "coverage_pct": coverage,
        }

    if (
        score is not None
        and coverage is not None
        and score >= float(pretrigger_score)
        and coverage >= float(pretrigger_coverage)
        and "CONFIRM" not in decision
    ):
        return {
            "alert": True,
            "state": "PRE_TRIGGER",
            "priority": 2,
            "symbol": symbol,
            "direction": direction,
            "score": score,
            "coverage_pct": coverage,
            "decision": decision,
            "reason": "Quality is building, but confirmation is not complete yet.",
        }

    return {
        "alert": False,
        "state": "WATCH",
        "symbol": symbol,
        "direction": direction,
        "score": score,
        "coverage_pct": coverage,
    }


def _money(value: Any) -> str:
    parsed = _number(value)
    return "—" if parsed is None else f"${parsed:,.2f}"


def build_discord_message(payload: dict[str, Any], classification: dict[str, Any]) -> dict[str, Any]:
    technical = payload.get("technical") or {}
    plan = payload.get("trade_plan") or {}
    fusion = payload.get("fusion_score") or {}
    gamma = payload.get("gamma") or {}
    flow = payload.get("flow") or {}
    options = payload.get("options") or []

    symbol = classification.get("symbol") or payload.get("symbol") or "?"
    direction = classification.get("direction") or fusion.get("direction") or "?"
    state = classification.get("state") or "WATCH"
    score = _number(fusion.get("score"))
    coverage = _number(fusion.get("coverage_pct"))
    price = _number(technical.get("price"))
    entry_low = _number(plan.get("entry_low") or technical.get("entry_low"))
    entry_high = _number(plan.get("entry_high") or technical.get("entry_high"))
    stop = _number(plan.get("stop") or plan.get("stop_price"))
    target = _number(plan.get("tp1") or plan.get("target1") or plan.get("target_1"))
    no_chase = (payload.get("execution_gate") or {}).get("no_chase") or {}
    chase_limit = _number(no_chase.get("limit"))

    title = f"{'🟡 PRE-TRIGGER' if state == 'PRE_TRIGGER' else '🟢 READY'} • {symbol} • {direction}"
    lines = [
        f"**MnT score:** {score:.0f}/100" if score is not None else "**MnT score:** —",
        f"**Data coverage:** {coverage:.0f}%" if coverage is not None else "**Data coverage:** —",
        f"**Stock price:** {_money(price)}",
    ]
    if entry_low is not None or entry_high is not None:
        lines.append(f"**Entry area:** {_money(entry_low)} – {_money(entry_high)}")
    if chase_limit is not None:
        lines.append(f"**Do not chase past:** {_money(chase_limit)}")
    if stop is not None:
        lines.append(f"**Risk line:** {_money(stop)}")
    if target is not None:
        lines.append(f"**First target:** {_money(target)}")

    if gamma.get("available"):
        gamma_bits = []
        if gamma.get("gamma_flip") is not None:
            gamma_bits.append(f"flip {_money(gamma.get('gamma_flip'))}")
        if gamma.get("call_wall") is not None:
            gamma_bits.append(f"call wall {_money(gamma.get('call_wall'))}")
        if gamma.get("put_wall") is not None:
            gamma_bits.append(f"put wall {_money(gamma.get('put_wall'))}")
        if gamma_bits:
            lines.append(f"**Gamma:** {', '.join(gamma_bits)}")

    if flow.get("available"):
        lines.append(f"**Options flow:** {str(flow.get('sentiment') or 'MIXED').upper()}")

    if options and state == "READY":
        option = options[0] or {}
        contract = option.get("symbol") or option.get("contract_symbol") or option.get("option_symbol")
        ask = _number(option.get("ask") or option.get("ask_price"))
        if contract:
            lines.append(f"**Option to review:** `{contract}`{f' (~${ask * 100:,.0f}/contract at ask)' if ask is not None else ''}")

    if state == "PRE_TRIGGER":
        lines.append("**Action now:** Watch the entry area. Do not buy yet; MnT is warning you before confirmation so you are not late.")
    else:
        lines.append("**Action now:** Entry review gates passed. Re-check price/no-chase level before acting.")

    lines.append("_Research alert only. MnT did not place an order._")
    return {
        "content": None,
        "embeds": [
            {
                "title": title,
                "description": "\n".join(lines),
            }
        ],
    }
