from __future__ import annotations

from typing import Any


def _number(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed == parsed else None


def _pick(mapping: dict[str, Any] | None, *keys: str) -> Any:
    if not isinstance(mapping, dict):
        return None
    for key in keys:
        value = mapping.get(key)
        if value not in (None, ""):
            return value
    return None


def _decision_label(value: Any) -> str:
    if isinstance(value, str):
        return value.strip().upper()
    if isinstance(value, dict):
        for key in ("decision", "action", "state", "status"):
            if value.get(key):
                return str(value[key]).strip().upper()
    return "UNKNOWN"


def equity_quote_snapshot(payload: dict[str, Any] | None) -> dict[str, float | None]:
    root = payload or {}
    quote = root.get("quote") if isinstance(root.get("quote"), dict) else root.get("regular") if isinstance(root.get("regular"), dict) else root
    bid = _number(_pick(quote, "bidPrice", "bid", "bid_price"))
    ask = _number(_pick(quote, "askPrice", "ask", "ask_price"))
    mark = _number(_pick(quote, "mark", "markPrice"))
    last = _number(_pick(quote, "lastPrice", "last", "closePrice", "close"))
    midpoint = (bid + ask) / 2.0 if bid and ask and bid > 0 and ask > 0 else None
    current = mark if mark and mark > 0 else midpoint if midpoint and midpoint > 0 else last
    return {"bid": bid, "ask": ask, "mark": mark, "last": last, "current": current}


def _trade_level(trade_plan: dict[str, Any] | None, *keys: str) -> float | None:
    return _number(_pick(trade_plan, *keys))


def build_stock_position_analysis(
    item: dict[str, Any],
    quote_payload: dict[str, Any] | None,
    *,
    fusion: dict[str, Any] | None = None,
) -> dict[str, Any]:
    symbol = str(item.get("symbol") or "").strip().upper()
    direction = str(item.get("direction") or "AUTO").strip().upper()
    if direction not in {"LONG", "SHORT"}:
        direction = "LONG"

    entry = _number(item.get("entry_price")) or 0.0
    shares = _number(item.get("shares")) or 0.0
    quote = equity_quote_snapshot(quote_payload)
    current = quote.get("current") or 0.0
    exit_reference = quote.get("bid") if direction == "LONG" else quote.get("ask")
    if not exit_reference or exit_reference <= 0:
        exit_reference = current

    cost_basis = entry * shares if entry > 0 and shares > 0 else None
    market_value = current * shares if current > 0 and shares > 0 else None
    if direction == "LONG":
        pnl_pct = ((exit_reference / entry) - 1.0) * 100.0 if entry > 0 and exit_reference > 0 else None
        pnl_dollars = (exit_reference - entry) * shares if entry > 0 and shares > 0 and exit_reference > 0 else None
        recovery_needed_pct = ((entry / current) - 1.0) * 100.0 if 0 < current < entry else 0.0 if current >= entry > 0 else None
        checkpoint = lambda pct: entry * (1.0 + pct)
    else:
        pnl_pct = ((entry - exit_reference) / entry) * 100.0 if entry > 0 and exit_reference > 0 else None
        pnl_dollars = (entry - exit_reference) * shares if entry > 0 and shares > 0 and exit_reference > 0 else None
        recovery_needed_pct = ((current - entry) / current) * 100.0 if current > entry > 0 else 0.0 if 0 < current <= entry else None
        checkpoint = lambda pct: entry * (1.0 - pct)

    technical = fusion.get("technical") if isinstance(fusion, dict) and isinstance(fusion.get("technical"), dict) else {}
    kronos = fusion.get("kronos") if isinstance(fusion, dict) and isinstance(fusion.get("kronos"), dict) else {}
    trade_plan = fusion.get("trade_plan") if isinstance(fusion, dict) and isinstance(fusion.get("trade_plan"), dict) else {}
    decision = _decision_label(fusion.get("decision")) if isinstance(fusion, dict) else "UNKNOWN"
    technical_signal = str(technical.get("signal") or "").upper()
    kronos_bias = str(kronos.get("final_bias") or "").upper()
    expected_kronos = "BULLISH" if direction == "LONG" else "BEARISH"

    thesis_conflict = False
    conflict_reasons: list[str] = []
    if technical_signal in {"LONG", "SHORT"} and technical_signal != direction:
        thesis_conflict = True
        conflict_reasons.append(f"5-minute technical direction is {technical_signal}, opposite this {direction} stock position.")
    if kronos_bias in {"BULLISH", "BEARISH"} and kronos_bias != expected_kronos:
        thesis_conflict = True
        conflict_reasons.append(f"Kronos bias is {kronos_bias}, opposite this {direction} stock position.")

    invalidation = _trade_level(trade_plan, "stop", "stop_price", "stop_loss", "stopLoss")
    target1 = _trade_level(trade_plan, "tp1", "target1", "target_1", "take_profit_1")
    target2 = _trade_level(trade_plan, "tp2", "target2", "target_2", "take_profit_2")
    target3 = _trade_level(trade_plan, "tp3", "target3", "target_3", "take_profit_3")
    if invalidation is None:
        invalidation = _number(technical.get("recent_low")) if direction == "LONG" else _number(technical.get("recent_high"))
    if target1 is None:
        target1 = _number(technical.get("recent_high")) if direction == "LONG" else _number(technical.get("recent_low"))

    structure_broken = False
    if current > 0 and invalidation is not None:
        structure_broken = current < invalidation if direction == "LONG" else current > invalidation

    state = "HOLD_WATCH"
    headline = "Position is near your cost basis."
    next_step = "Keep watching the underlying structure. Run Analyze Position for the current Kronos thesis and structural exit levels."
    if structure_broken:
        state = "EXIT_REVIEW"
        headline = "Price has crossed the current structural invalidation level."
        next_step = "Review reducing or exiting the position. Do not hold only because you want price to return to your entry."
    elif thesis_conflict:
        state = "EXIT_REVIEW"
        headline = "The current MnT thesis conflicts with this stock position."
        next_step = "Review the position now. Protect capital or open profit rather than assuming the original thesis will recover."
    elif pnl_pct is not None and pnl_pct >= 25:
        state = "TAKE_PROFIT"
        headline = "The stock has a substantial open gain from your entry."
        next_step = "Consider taking partial profit and manage the remainder with the structural invalidation level."
    elif pnl_pct is not None and pnl_pct >= 12:
        state = "PROTECT_PROFIT"
        headline = "The position is working; protect the gain."
        next_step = "Keep the position while the underlying thesis remains constructive, but tighten your risk so a large open gain does not turn into a loss."
    elif pnl_pct is not None and pnl_pct >= 3:
        state = "WORKING"
        headline = "The position is working."
        next_step = "Hold while structure and Kronos remain aligned. Use Analyze Position to refresh targets and invalidation."
    elif pnl_pct is not None and pnl_pct <= -15:
        state = "RISK_OFF"
        headline = "The stock is materially below your entry."
        next_step = "Reassess the thesis now. Do not add simply to lower average cost; protect remaining capital if the structure is broken."
    elif pnl_pct is not None and pnl_pct <= -7:
        state = "UNDER_PRESSURE"
        headline = "The stock position is under pressure."
        next_step = "Hold only if the underlying thesis remains valid. Define the structural invalidation before deciding whether to stay in."

    protect_profit_reference = None
    if entry > 0 and pnl_pct is not None:
        if direction == "LONG":
            if pnl_pct >= 25:
                protect_profit_reference = entry * 1.10
            elif pnl_pct >= 12:
                protect_profit_reference = entry
        else:
            if pnl_pct >= 25:
                protect_profit_reference = entry * 0.90
            elif pnl_pct >= 12:
                protect_profit_reference = entry

    return {
        "symbol": symbol,
        "direction": direction,
        "shares": round(shares, 6) if shares else None,
        "entry_price": round(entry, 4) if entry else None,
        "current": {
            "price": round(current, 4) if current else None,
            "bid": round(float(quote["bid"]), 4) if quote.get("bid") else None,
            "ask": round(float(quote["ask"]), 4) if quote.get("ask") else None,
            "exit_reference": round(float(exit_reference), 4) if exit_reference else None,
        },
        "pnl": {
            "pct": round(pnl_pct, 2) if pnl_pct is not None else None,
            "dollars": round(pnl_dollars, 2) if pnl_dollars is not None else None,
            "cost_basis": round(cost_basis, 2) if cost_basis is not None else None,
            "market_value": round(market_value, 2) if market_value is not None else None,
            "recovery_needed_pct": round(recovery_needed_pct, 2) if recovery_needed_pct is not None else None,
        },
        "key_levels": {
            "underlying_invalidation": round(invalidation, 4) if invalidation is not None else None,
            "underlying_target_1": round(target1, 4) if target1 is not None else None,
            "underlying_target_2": round(target2, 4) if target2 is not None else None,
            "underlying_target_3": round(target3, 4) if target3 is not None else None,
            "price_checkpoint_5": round(checkpoint(0.05), 4) if entry > 0 else None,
            "price_checkpoint_10": round(checkpoint(0.10), 4) if entry > 0 else None,
            "price_checkpoint_20": round(checkpoint(0.20), 4) if entry > 0 else None,
            "protect_profit_reference": round(protect_profit_reference, 4) if protect_profit_reference is not None else None,
        },
        "thesis": {
            "technical_signal": technical_signal or None,
            "kronos_bias": kronos_bias or None,
            "decision": decision,
            "conflict": thesis_conflict,
            "conflict_reasons": conflict_reasons,
            "structure_broken": structure_broken,
        },
        "management": {
            "state": state,
            "headline": headline,
            "next_step": next_step,
            "note": "Research-only stock position management. Current exit value uses bid for long shares and ask for short shares when available.",
        },
        "research_only": True,
        "order_submission_enabled": False,
    }
