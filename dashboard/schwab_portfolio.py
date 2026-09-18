from __future__ import annotations

import re
from typing import Any

_OPTION_RE = re.compile(r"^([A-Z0-9.\-]+)\s+\d{6}([CP])\d+$")


def underlying_symbol(symbol: Any, asset_type: Any = None) -> str:
    raw = str(symbol or "").strip().upper()
    kind = str(asset_type or "").strip().upper()
    if not raw:
        return ""
    if kind == "OPTION" or " " in raw:
        match = _OPTION_RE.match(raw)
        if match:
            return match.group(1)
        return raw.split()[0]
    return raw


def option_side(symbol: Any) -> str | None:
    raw = str(symbol or "").strip().upper()
    match = _OPTION_RE.match(raw)
    if not match:
        return None
    return "CALL" if match.group(2) == "C" else "PUT"


def _number(value: Any) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return 0.0
    return result if result == result else 0.0


def _position_direction(row: dict[str, Any]) -> int:
    """Return +1 bullish, -1 bearish, 0 unknown/mixed for a position row."""
    long_qty = _number(row.get("long_quantity"))
    short_qty = _number(row.get("short_quantity"))
    net_qty = long_qty - short_qty
    if net_qty == 0:
        return 0

    asset = str(row.get("asset_type") or "").upper()
    if asset == "OPTION":
        side = option_side(row.get("symbol"))
        if side == "CALL":
            return 1 if net_qty > 0 else -1
        if side == "PUT":
            return -1 if net_qty > 0 else 1
        return 0
    return 1 if net_qty > 0 else -1


def build_symbol_context(
    portfolio: dict[str, Any] | None,
    symbol: str,
    *,
    intended_direction: str | None = None,
) -> dict[str, Any]:
    target = str(symbol or "").strip().upper()
    direction = str(intended_direction or "").strip().upper()
    accounts = list((portfolio or {}).get("accounts") or [])

    matches: list[dict[str, Any]] = []
    total_liquidation = 0.0
    total_buying_power = 0.0
    bullish_value = 0.0
    bearish_value = 0.0

    for account in accounts:
        balances = account.get("balances") or {}
        total_liquidation += _number(balances.get("liquidation_value"))
        total_buying_power += _number(balances.get("buying_power"))
        for row in account.get("positions") or []:
            if underlying_symbol(row.get("symbol"), row.get("asset_type")) != target:
                continue
            position = {
                "account": account.get("account"),
                "symbol": row.get("symbol"),
                "underlying": target,
                "asset_type": row.get("asset_type"),
                "option_side": option_side(row.get("symbol")) if str(row.get("asset_type") or "").upper() == "OPTION" else None,
                "long_quantity": row.get("long_quantity"),
                "short_quantity": row.get("short_quantity"),
                "average_price": row.get("average_price"),
                "market_value": row.get("market_value"),
                "current_day_profit_loss": row.get("current_day_profit_loss"),
                "current_day_profit_loss_pct": row.get("current_day_profit_loss_pct"),
            }
            matches.append(position)
            exposure = _position_direction(row)
            value = abs(_number(row.get("market_value")))
            if exposure > 0:
                bullish_value += value
            elif exposure < 0:
                bearish_value += value

    if not matches:
        exposure_state = "NONE"
    elif bullish_value > 0 and bearish_value > 0:
        dominant = max(bullish_value, bearish_value)
        minor = min(bullish_value, bearish_value)
        exposure_state = "MIXED" if minor >= dominant * 0.25 else ("BULLISH" if bullish_value > bearish_value else "BEARISH")
    else:
        exposure_state = "BULLISH" if bullish_value > bearish_value else "BEARISH"

    existing_value = bullish_value + bearish_value
    concentration_pct = (existing_value / total_liquidation * 100.0) if total_liquidation > 0 else 0.0

    if exposure_state == "NONE":
        relationship = "NEW"
        action_note = f"No existing {target} position was found in the connected Schwab accounts."
    elif direction in {"LONG", "SHORT"}:
        desired = "BULLISH" if direction == "LONG" else "BEARISH"
        if exposure_state == desired:
            relationship = "ALREADY_EXPOSED"
            action_note = f"You already have {desired.lower()} {target} exposure. MnT should treat a new setup as an add-on decision, not a fresh trade."
        elif exposure_state in {"BULLISH", "BEARISH"}:
            relationship = "CONFLICT"
            action_note = f"Your existing {target} exposure points the opposite way from this setup. MnT should flag this as a hedge/conflict before adding risk."
        else:
            relationship = "MIXED"
            action_note = f"You already have mixed {target} exposure. Review the existing positions before adding another trade."
    else:
        relationship = exposure_state
        action_note = f"Existing {target} exposure is {exposure_state.lower()}."

    risk_level = "LOW"
    if concentration_pct >= 20:
        risk_level = "HIGH"
    elif concentration_pct >= 10:
        risk_level = "ELEVATED"
    elif concentration_pct >= 5:
        risk_level = "MODERATE"

    return {
        "symbol": target,
        "intended_direction": direction or None,
        "relationship": relationship,
        "exposure_state": exposure_state,
        "existing_position_count": len(matches),
        "existing_market_value": round(existing_value, 2),
        "bullish_market_value": round(bullish_value, 2),
        "bearish_market_value": round(bearish_value, 2),
        "portfolio_liquidation_value": round(total_liquidation, 2),
        "buying_power": round(total_buying_power, 2),
        "concentration_pct": round(concentration_pct, 2),
        "risk_level": risk_level,
        "positions": matches,
        "action_note": action_note,
        "read_only": True,
    }
