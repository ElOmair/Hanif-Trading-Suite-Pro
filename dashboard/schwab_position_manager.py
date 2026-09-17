from __future__ import annotations

from typing import Any, Mapping

from schwab_portfolio import option_side, underlying_symbol


def _number(value: Any) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return 0.0
    return result if result == result else 0.0


def _net_quantity(row: Mapping[str, Any]) -> float:
    return _number(row.get("long_quantity")) - _number(row.get("short_quantity"))


def _exposure_direction(row: Mapping[str, Any]) -> str:
    net = _net_quantity(row)
    if net == 0:
        return "NEUTRAL"
    asset = str(row.get("asset_type") or "").upper()
    if asset == "OPTION":
        side = option_side(row.get("symbol"))
        if side == "CALL":
            return "LONG" if net > 0 else "SHORT"
        if side == "PUT":
            return "SHORT" if net > 0 else "LONG"
    return "LONG" if net > 0 else "SHORT"


def _open_pnl(row: Mapping[str, Any]) -> float | None:
    direct = row.get("unrealized_profit_loss")
    if direct is not None:
        return _number(direct)
    values = [row.get("long_open_profit_loss"), row.get("short_open_profit_loss")]
    if any(value is not None for value in values):
        return sum(_number(value) for value in values)
    return None


def _estimated_cost_basis(row: Mapping[str, Any]) -> float:
    long_qty = _number(row.get("long_quantity"))
    short_qty = _number(row.get("short_quantity"))
    qty = abs(long_qty - short_qty)
    if qty <= 0:
        return 0.0
    avg = _number(
        row.get("average_long_price") if long_qty > short_qty else row.get("average_short_price")
    ) or _number(row.get("average_price"))
    multiplier = 100.0 if str(row.get("asset_type") or "").upper() == "OPTION" else 1.0
    return abs(qty * avg * multiplier)


def _estimated_open_return_pct(row: Mapping[str, Any]) -> float | None:
    pnl = _open_pnl(row)
    basis = _estimated_cost_basis(row)
    if pnl is None or basis <= 0:
        return None
    return pnl / basis * 100.0


def _technical_direction(technical: Mapping[str, Any] | None) -> str:
    signal = str((technical or {}).get("signal") or "").upper()
    return signal if signal in {"LONG", "SHORT", "NEUTRAL"} else "UNKNOWN"


def review_position(
    row: Mapping[str, Any],
    *,
    liquidation_value: float,
    technical: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    asset = str(row.get("asset_type") or "").upper()
    symbol = str(row.get("symbol") or "")
    underlying = underlying_symbol(symbol, asset)
    exposure = _exposure_direction(row)
    tech_direction = _technical_direction(technical)
    market_value = abs(_number(row.get("market_value")))
    concentration = market_value / liquidation_value * 100.0 if liquidation_value > 0 else 0.0
    open_pnl = _open_pnl(row)
    return_pct = _estimated_open_return_pct(row)

    state = "HOLD"
    priority = 30
    headline = "No immediate change is required from the information MnT has."
    explanation = "The position is not showing a strong enough risk or profit-management signal to force an action."

    opposed = (
        exposure in {"LONG", "SHORT"}
        and tech_direction in {"LONG", "SHORT"}
        and exposure != tech_direction
    )

    if opposed and return_pct is not None and return_pct <= -10.0:
        state = "REVIEW_EXIT"
        priority = 100
        headline = "The position is losing money and the current MnT direction points the other way."
        explanation = "Review the exit instead of adding more or hoping the setup reverses. This is a risk-control signal, not an automatic order."
    elif asset == "OPTION" and return_pct is not None and return_pct <= -25.0:
        state = "REVIEW_EXIT"
        priority = 95
        headline = "The option has lost a meaningful part of its original cost."
        explanation = "Options can keep losing value even when the stock later recovers. Review whether the original thesis still justifies keeping the contract."
    elif opposed:
        state = "PROTECT"
        priority = 85
        headline = "The current MnT direction is fighting your existing position."
        explanation = "Avoid adding more risk until the chart and your position agree again. Consider tightening protection or reducing exposure."
    elif asset == "OPTION" and return_pct is not None and return_pct >= 30.0:
        state = "TAKE_SOME_PROFIT"
        priority = 80
        headline = "The option has a meaningful open gain."
        explanation = "Consider taking part of the profit instead of making the entire result depend on the next move. MnT is not submitting a sell order."
    elif asset != "OPTION" and return_pct is not None and return_pct >= 15.0:
        state = "TAKE_SOME_PROFIT"
        priority = 70
        headline = "The stock position has built a meaningful open gain."
        explanation = "Partial profit-taking may reduce risk while keeping some exposure if the longer trend continues."
    elif concentration >= 20.0:
        state = "DO_NOT_ADD"
        priority = 75
        headline = "This position is already a large part of the connected portfolio."
        explanation = "Even if the setup still looks good, adding more would increase concentration risk."
    elif tech_direction == exposure and exposure in {"LONG", "SHORT"}:
        state = "HOLD"
        priority = 40
        headline = "The current MnT direction still agrees with the position."
        explanation = "The setup remains aligned for now. Continue monitoring rather than changing the position just to stay active."

    return {
        "symbol": symbol,
        "underlying": underlying,
        "asset_type": asset or None,
        "exposure_direction": exposure,
        "technical_direction": tech_direction,
        "state": state,
        "priority": priority,
        "headline": headline,
        "explanation": explanation,
        "market_value": round(market_value, 2),
        "concentration_pct": round(concentration, 2),
        "open_profit_loss": round(open_pnl, 2) if open_pnl is not None else None,
        "estimated_open_return_pct": round(return_pct, 2) if return_pct is not None else None,
        "current_day_profit_loss": row.get("current_day_profit_loss"),
        "current_day_profit_loss_pct": row.get("current_day_profit_loss_pct"),
        "average_price": row.get("average_price"),
        "long_quantity": row.get("long_quantity"),
        "short_quantity": row.get("short_quantity"),
        "research_only": True,
    }


def build_portfolio_reviews(
    portfolio: Mapping[str, Any] | None,
    *,
    technical_by_symbol: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    accounts = list((portfolio or {}).get("accounts") or [])
    liquidation_value = sum(_number((account.get("balances") or {}).get("liquidation_value")) for account in accounts)
    technical_by_symbol = technical_by_symbol or {}
    reviews: list[dict[str, Any]] = []

    for account in accounts:
        for row in account.get("positions") or []:
            underlying = underlying_symbol(row.get("symbol"), row.get("asset_type"))
            review = review_position(
                row,
                liquidation_value=liquidation_value,
                technical=technical_by_symbol.get(underlying),
            )
            review["account"] = account.get("account")
            reviews.append(review)

    reviews.sort(key=lambda item: (int(item.get("priority") or 0), abs(float(item.get("market_value") or 0.0))), reverse=True)
    attention = [item for item in reviews if item["state"] != "HOLD"]
    return {
        "provider": "schwab",
        "position_count": len(reviews),
        "attention_count": len(attention),
        "portfolio_liquidation_value": round(liquidation_value, 2),
        "reviews": reviews,
        "research_only": True,
        "order_submission_enabled": False,
        "note": "These are portfolio-management prompts, not automatic brokerage instructions.",
    }
