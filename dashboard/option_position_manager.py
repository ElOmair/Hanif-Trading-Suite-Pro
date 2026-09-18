from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from schwab_contracts import flatten_chain


def _number(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed == parsed else None


def _pick(obj: dict[str, Any] | None, *keys: str) -> Any:
    if not isinstance(obj, dict):
        return None
    for key in keys:
        value = obj.get(key)
        if value not in (None, ""):
            return value
    return None


def _expiration_text(contract: dict[str, Any]) -> str | None:
    raw = contract.get("expirationDate")
    if raw is not None:
        try:
            value = float(raw)
            if value > 10_000_000_000:
                value /= 1000.0
            return datetime.fromtimestamp(value, tz=timezone.utc).date().isoformat()
        except (TypeError, ValueError, OSError):
            pass
    text = str(contract.get("expiration") or contract.get("expirationDateText") or "").strip()
    if not text:
        return None
    return text.split(":", 1)[0]


def parse_occ_symbol(value: str | None) -> dict[str, Any] | None:
    """Parse a standard OCC option symbol such as HOOD 261016C00065000.

    Spaces in OCC symbols are optional here because Schwab descriptions and user
    copy/paste formats are not always padded the same way.
    """
    compact = re.sub(r"\s+", "", str(value or "").upper())
    match = re.fullmatch(r"([A-Z.\-]{1,10})(\d{6})([CP])(\d{8})", compact)
    if not match:
        return None
    root, yymmdd, cp, strike_raw = match.groups()
    try:
        expiry = datetime.strptime(yymmdd, "%y%m%d").date().isoformat()
    except ValueError:
        return None
    return {
        "underlying": root,
        "expiration": expiry,
        "option_type": "CALL" if cp == "C" else "PUT",
        "strike": int(strike_raw) / 1000.0,
        "contract_symbol": str(value or "").strip().upper(),
    }


def option_spec_from_focus(item: dict[str, Any]) -> dict[str, Any]:
    parsed = parse_occ_symbol(str(item.get("contract") or "")) or {}
    option_type = str(item.get("option_type") or parsed.get("option_type") or "").strip().upper()
    if option_type in {"C", "CALLS"}:
        option_type = "CALL"
    if option_type in {"P", "PUTS"}:
        option_type = "PUT"
    strike = _number(item.get("strike"))
    if strike is None:
        strike = _number(parsed.get("strike"))
    expiration = str(item.get("expiration") or parsed.get("expiration") or "").strip() or None
    quantity = int(_number(item.get("quantity")) or 1)
    return {
        "symbol": str(item.get("symbol") or parsed.get("underlying") or "").strip().upper(),
        "option_type": option_type if option_type in {"CALL", "PUT"} else None,
        "strike": strike,
        "expiration": expiration,
        "quantity": max(1, quantity),
        "entry_price": _number(item.get("entry_price")),
        "contract_symbol": str(item.get("contract") or parsed.get("contract_symbol") or "").strip().upper() or None,
    }


def missing_option_fields(item: dict[str, Any]) -> list[str]:
    spec = option_spec_from_focus(item)
    required = ("option_type", "strike", "expiration", "entry_price")
    return [field for field in required if spec.get(field) in (None, "")]


def find_exact_contract(chain: dict[str, Any], spec: dict[str, Any]) -> dict[str, Any] | None:
    option_type = str(spec.get("option_type") or "").upper()
    direction = "LONG" if option_type == "CALL" else "SHORT"
    target_strike = _number(spec.get("strike"))
    target_expiration = str(spec.get("expiration") or "")
    target_symbol = re.sub(r"\s+", "", str(spec.get("contract_symbol") or "").upper())
    for contract in flatten_chain(chain, direction):
        contract_symbol = re.sub(r"\s+", "", str(contract.get("symbol") or "").upper())
        contract_strike = _number(contract.get("strikePrice"))
        contract_expiration = _expiration_text(contract)
        if target_symbol and contract_symbol and target_symbol == contract_symbol:
            return contract
        if (
            target_strike is not None
            and contract_strike is not None
            and abs(target_strike - contract_strike) < 0.001
            and target_expiration
            and contract_expiration == target_expiration
        ):
            return contract
    return None


def underlying_price_from_chain(chain: dict[str, Any]) -> float | None:
    direct = _number(chain.get("underlyingPrice"))
    if direct and direct > 0:
        return direct
    underlying = chain.get("underlying") if isinstance(chain.get("underlying"), dict) else {}
    for key in ("mark", "last", "lastPrice", "close"):
        value = _number(underlying.get(key))
        if value and value > 0:
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


def _trade_level(trade_plan: dict[str, Any] | None, *keys: str) -> float | None:
    value = _pick(trade_plan, *keys)
    return _number(value)


def build_option_position_analysis(
    item: dict[str, Any],
    contract: dict[str, Any],
    *,
    underlying_price: float | None = None,
    fusion: dict[str, Any] | None = None,
) -> dict[str, Any]:
    spec = option_spec_from_focus(item)
    entry = float(spec["entry_price"] or 0.0)
    quantity = int(spec.get("quantity") or 1)
    option_type = str(spec.get("option_type") or "").upper()
    strike = float(spec.get("strike") or 0.0)

    bid = _number(contract.get("bid")) or 0.0
    ask = _number(contract.get("ask")) or 0.0
    raw_mark = _number(contract.get("mark"))
    midpoint = (bid + ask) / 2.0 if bid > 0 and ask > 0 else None
    mark = raw_mark if raw_mark and raw_mark > 0 else midpoint or _number(contract.get("last")) or 0.0
    conservative_exit = bid if bid > 0 else mark
    spread_pct = ((ask - bid) / midpoint * 100.0) if midpoint and ask >= bid else None

    mark_pnl_pct = ((mark / entry) - 1.0) * 100.0 if entry > 0 and mark > 0 else None
    exit_pnl_pct = ((conservative_exit / entry) - 1.0) * 100.0 if entry > 0 and conservative_exit > 0 else None
    mark_pnl_dollars = (mark - entry) * 100.0 * quantity if mark > 0 and entry > 0 else None
    exit_pnl_dollars = (conservative_exit - entry) * 100.0 * quantity if conservative_exit > 0 and entry > 0 else None
    recovery_needed_pct = ((entry / mark) - 1.0) * 100.0 if 0 < mark < entry else 0.0 if mark >= entry > 0 else None

    dte = int(_number(contract.get("daysToExpiration")) or 0)
    delta = _number(contract.get("delta"))
    theta = _number(contract.get("theta"))
    gamma = _number(contract.get("gamma"))
    vega = _number(contract.get("vega"))
    iv = _number(contract.get("volatility"))
    theta_pct_per_day = abs(theta) / mark * 100.0 if theta is not None and mark > 0 else None

    intrinsic = None
    if underlying_price is not None and strike > 0:
        intrinsic = max(0.0, underlying_price - strike) if option_type == "CALL" else max(0.0, strike - underlying_price)
    extrinsic = max(0.0, mark - intrinsic) if intrinsic is not None and mark > 0 else None
    expiry_breakeven = strike + entry if option_type == "CALL" else strike - entry if option_type == "PUT" else None

    expected_signal = "LONG" if option_type == "CALL" else "SHORT"
    expected_kronos = "BULLISH" if option_type == "CALL" else "BEARISH"
    technical = fusion.get("technical") if isinstance(fusion, dict) and isinstance(fusion.get("technical"), dict) else {}
    kronos = fusion.get("kronos") if isinstance(fusion, dict) and isinstance(fusion.get("kronos"), dict) else {}
    trade_plan = fusion.get("trade_plan") if isinstance(fusion, dict) and isinstance(fusion.get("trade_plan"), dict) else {}
    decision = _decision_label(fusion.get("decision")) if isinstance(fusion, dict) else "UNKNOWN"
    technical_signal = str(technical.get("signal") or "").upper()
    kronos_bias = str(kronos.get("final_bias") or "").upper()

    thesis_conflict = False
    conflict_reasons: list[str] = []
    if technical_signal in {"LONG", "SHORT"} and technical_signal != expected_signal:
        thesis_conflict = True
        conflict_reasons.append(f"5-minute technical direction is {technical_signal}, opposite this {option_type}.")
    if kronos_bias in {"BULLISH", "BEARISH"} and kronos_bias != expected_kronos:
        thesis_conflict = True
        conflict_reasons.append(f"Kronos bias is {kronos_bias}, opposite this {option_type}.")
    if "REJECT" in decision:
        thesis_conflict = True
        conflict_reasons.append("The current MnT decision engine rejects a fresh setup in this direction.")

    risk_flags: list[str] = []
    if spread_pct is not None and spread_pct >= 10:
        risk_flags.append(f"Wide option spread ({spread_pct:.1f}%) can make exits expensive.")
    if dte <= 3:
        risk_flags.append(f"Only {dte} DTE remains; time decay and gamma risk are high.")
    elif dte <= 7:
        risk_flags.append(f"Only {dte} DTE remains; time decay is becoming important.")
    if theta_pct_per_day is not None and theta_pct_per_day >= 5:
        risk_flags.append(f"Quoted theta is about {theta_pct_per_day:.1f}% of current premium per day.")
    if iv is not None and iv >= 100:
        risk_flags.append(f"Implied volatility is elevated ({iv:.1f}%). A volatility drop can hurt premium even if the stock moves modestly your way.")

    pnl_for_state = exit_pnl_pct if exit_pnl_pct is not None else mark_pnl_pct
    state = "HOLD_WATCH"
    headline = "Position is near your cost basis."
    next_step = "Keep the position only while the underlying thesis remains valid; do not average down solely to lower your cost basis."

    if thesis_conflict:
        state = "EXIT_REVIEW"
        headline = "The current underlying thesis conflicts with this option."
        next_step = "Review an exit or meaningful risk reduction. Do not wait for the premium to return to your entry simply because that is your cost basis."
    elif dte <= 2 and (pnl_for_state is None or pnl_for_state < 15):
        state = "TIME_RISK"
        headline = "Expiration risk is now dominating the position."
        next_step = "Prioritize capital protection. The option needs an immediate underlying move; holding only to hope for breakeven is not a plan."
    elif pnl_for_state is not None and pnl_for_state >= 50:
        state = "TAKE_PROFIT"
        headline = "The option has a substantial open profit."
        next_step = (
            "Consider taking 25–50% off and manage the remainder with the underlying invalidation level."
            if quantity >= 2
            else "With one contract, consider taking the profit or trailing the position using the underlying invalidation level rather than giving the full gain back."
        )
    elif pnl_for_state is not None and pnl_for_state >= 20:
        state = "PROTECT_PROFIT"
        headline = "The position is working; protect the gain."
        next_step = (
            "Consider taking one contract off or tightening risk on the remaining contracts."
            if quantity >= 2
            else "Keep the contract only while the underlying stays constructive; use the underlying invalidation level as the primary exit signal."
        )
    elif pnl_for_state is not None and pnl_for_state >= 5:
        state = "WORKING"
        headline = "The position is working."
        next_step = "Hold while the underlying remains aligned. Avoid adding just because the option is green; protect the trade if structure deteriorates."
    elif pnl_for_state is not None and pnl_for_state <= -30:
        state = "RISK_OFF"
        headline = "The option is materially below your entry."
        next_step = "Reassess the thesis now. Do not average down automatically; if the underlying setup is broken or time is short, protect remaining capital."
    elif pnl_for_state is not None and pnl_for_state <= -12:
        state = "UNDER_PRESSURE"
        headline = "The option is under pressure."
        next_step = "Hold only if the underlying thesis is still intact and enough time remains. Define the invalidation before deciding whether to stay in."

    protect_profit_reference = None
    if entry > 0 and pnl_for_state is not None:
        if pnl_for_state >= 50:
            protect_profit_reference = entry * 1.25
        elif pnl_for_state >= 25:
            protect_profit_reference = entry * 1.10
        elif pnl_for_state >= 15:
            protect_profit_reference = entry

    stop = _trade_level(trade_plan, "stop", "stop_price", "stop_loss", "stopLoss")
    tp1 = _trade_level(trade_plan, "tp1", "target1", "target_1", "take_profit_1")
    tp2 = _trade_level(trade_plan, "tp2", "target2", "target_2", "take_profit_2")
    tp3 = _trade_level(trade_plan, "tp3", "target3", "target_3", "take_profit_3")
    if stop is None:
        # A live position should still have a visible structural reference even if
        # the external trade-plan module did not emit a stop key we recognize.
        stop = _number(technical.get("recent_low")) if option_type == "CALL" else _number(technical.get("recent_high"))

    return {
        "symbol": spec.get("symbol"),
        "contract_symbol": contract.get("symbol") or spec.get("contract_symbol"),
        "description": contract.get("description"),
        "option_type": option_type,
        "strike": strike,
        "expiration": spec.get("expiration") or _expiration_text(contract),
        "quantity": quantity,
        "entry_price": round(entry, 4),
        "current": {
            "bid": round(bid, 4) if bid else None,
            "ask": round(ask, 4) if ask else None,
            "mark": round(mark, 4) if mark else None,
            "last": _number(contract.get("last")),
            "conservative_exit": round(conservative_exit, 4) if conservative_exit else None,
            "spread_pct": round(spread_pct, 2) if spread_pct is not None else None,
            "underlying_price": round(float(underlying_price), 4) if underlying_price is not None else None,
        },
        "pnl": {
            "mark_pct": round(mark_pnl_pct, 2) if mark_pnl_pct is not None else None,
            "mark_dollars": round(mark_pnl_dollars, 2) if mark_pnl_dollars is not None else None,
            "exit_pct": round(exit_pnl_pct, 2) if exit_pnl_pct is not None else None,
            "exit_dollars": round(exit_pnl_dollars, 2) if exit_pnl_dollars is not None else None,
            "recovery_needed_pct": round(recovery_needed_pct, 2) if recovery_needed_pct is not None else None,
            "cost_basis": round(entry * 100.0 * quantity, 2),
            "mark_value": round(mark * 100.0 * quantity, 2) if mark > 0 else None,
        },
        "risk": {
            "days_to_expiration": dte,
            "delta": delta,
            "gamma": gamma,
            "theta": theta,
            "vega": vega,
            "iv": iv,
            "theta_pct_of_premium_per_day": round(theta_pct_per_day, 2) if theta_pct_per_day is not None else None,
            "intrinsic_value": round(intrinsic, 4) if intrinsic is not None else None,
            "extrinsic_value": round(extrinsic, 4) if extrinsic is not None else None,
            "open_interest": int(_number(contract.get("openInterest")) or 0),
            "volume": int(_number(contract.get("totalVolume")) or 0),
            "flags": risk_flags,
        },
        "key_levels": {
            "premium_breakeven": round(entry, 4),
            "profit_checkpoint_20": round(entry * 1.20, 4) if entry > 0 else None,
            "profit_checkpoint_40": round(entry * 1.40, 4) if entry > 0 else None,
            "profit_checkpoint_60": round(entry * 1.60, 4) if entry > 0 else None,
            "protect_profit_reference": round(protect_profit_reference, 4) if protect_profit_reference else None,
            "underlying_expiry_breakeven": round(expiry_breakeven, 4) if expiry_breakeven is not None else None,
            "underlying_invalidation": round(stop, 4) if stop is not None else None,
            "underlying_target_1": round(tp1, 4) if tp1 is not None else None,
            "underlying_target_2": round(tp2, 4) if tp2 is not None else None,
            "underlying_target_3": round(tp3, 4) if tp3 is not None else None,
        },
        "thesis": {
            "expected_technical": expected_signal,
            "technical_signal": technical_signal or None,
            "expected_kronos": expected_kronos,
            "kronos_bias": kronos_bias or None,
            "decision": decision if decision != "UNKNOWN" else None,
            "conflict": thesis_conflict,
            "conflict_reasons": conflict_reasons,
        },
        "management": {
            "state": state,
            "headline": headline,
            "next_step": next_step,
            "primary_exit_basis": "UNDERLYING_STRUCTURE",
            "note": "Premium checkpoints are reference levels, not guaranteed targets. MnT manages the option primarily from underlying structure, time remaining, and live option liquidity.",
        },
        "research_only": True,
    }
