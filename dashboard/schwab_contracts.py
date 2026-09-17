from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def _number(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed == parsed else None


def _expiration_text(contract: dict[str, Any]) -> str | None:
    raw = contract.get("expirationDate")
    if raw is not None:
        try:
            value = float(raw)
            # Schwab commonly returns epoch milliseconds here.
            if value > 10_000_000_000:
                value /= 1000.0
            return datetime.fromtimestamp(value, tz=timezone.utc).date().isoformat()
        except (TypeError, ValueError, OSError):
            pass
    text = str(contract.get("expiration") or contract.get("expirationDateText") or "").strip()
    return text or None


def flatten_chain(chain: dict[str, Any], direction: str) -> list[dict[str, Any]]:
    side = "callExpDateMap" if str(direction).upper() == "LONG" else "putExpDateMap"
    raw_map = chain.get(side) or {}
    rows: list[dict[str, Any]] = []
    if not isinstance(raw_map, dict):
        return rows
    for expiration_key, strikes in raw_map.items():
        if not isinstance(strikes, dict):
            continue
        expiration_hint = str(expiration_key).split(":", 1)[0]
        for strike_key, contracts in strikes.items():
            if not isinstance(contracts, list):
                continue
            for contract in contracts:
                if not isinstance(contract, dict):
                    continue
                item = dict(contract)
                item.setdefault("strikePrice", _number(strike_key))
                item.setdefault("expirationDateText", expiration_hint)
                rows.append(item)
    return rows


def _style_eligible(contract: dict[str, Any], style: str) -> tuple[bool, str | None]:
    """Apply hard style guardrails before ranking.

    A contract that is excellent for a 0DTE/intraday trade should not outrank a
    true swing contract merely because its spread and volume are better. Swing
    mode intentionally refuses near-expiry lottery-like contracts instead of
    forcing a candidate under the user's budget.
    """
    style = str(style or "auto").lower()
    dte = max(0.0, _number(contract.get("daysToExpiration")) or 0.0)
    delta = abs(_number(contract.get("delta")) or 0.0)

    if style == "0dte":
        if dte != 0:
            return False, "0DTE mode only accepts contracts expiring today."
    elif style in {"intraday", "day"}:
        if dte > 7:
            return False, "Intraday mode only accepts contracts with 0–7 DTE."
    elif style == "swing":
        if dte < 14 or dte > 90:
            return False, "Swing mode requires 14–90 DTE; 21–60 DTE is preferred."
        if delta and delta < 0.25:
            return False, "Swing mode rejects very low-delta contracts below 0.25."
    elif style == "position":
        if dte < 30 or dte > 180:
            return False, "Position mode requires 30–180 DTE."
        if delta and delta < 0.30:
            return False, "Position mode rejects low-delta contracts below 0.30."

    return True, None


def _fit_score(contract: dict[str, Any], *, style: str, max_contract_cost: float) -> tuple[float, dict[str, Any]]:
    bid = _number(contract.get("bid")) or 0.0
    ask = _number(contract.get("ask")) or 0.0
    delta = abs(_number(contract.get("delta")) or 0.0)
    volume = max(0.0, _number(contract.get("totalVolume")) or 0.0)
    oi = max(0.0, _number(contract.get("openInterest")) or 0.0)
    dte = max(0.0, _number(contract.get("daysToExpiration")) or 0.0)
    iv = max(0.0, _number(contract.get("volatility")) or 0.0)
    cost = ask * 100.0
    mid = (bid + ask) / 2.0 if bid > 0 and ask > 0 else 0.0
    spread_pct = ((ask - bid) / mid * 100.0) if mid > 0 and ask >= bid else None

    score = 50.0
    if ask <= 0 or cost > max_contract_cost:
        score -= 60.0
    else:
        score += 8.0

    if spread_pct is not None:
        if spread_pct <= 5:
            score += 16
        elif spread_pct <= 10:
            score += 8
        elif spread_pct <= 15:
            score -= 4
        else:
            score -= 16
    else:
        score -= 10

    if oi >= 1000:
        score += 12
    elif oi >= 250:
        score += 8
    elif oi >= 50:
        score += 3
    else:
        score -= 8

    if volume >= 500:
        score += 10
    elif volume >= 100:
        score += 6
    elif volume >= 20:
        score += 2
    elif volume <= 1:
        score -= 6

    style = str(style or "auto").lower()
    target_delta = 0.45 if style in {"intraday", "0dte", "day"} else 0.55 if style in {"swing", "position"} else 0.50
    score += max(-12.0, 12.0 - abs(delta - target_delta) * 60.0) if delta > 0 else -5.0

    if style in {"intraday", "0dte", "day"}:
        if dte <= 2:
            score += 10
        elif dte <= 7:
            score += 5
    elif style == "swing":
        if 21 <= dte <= 60:
            score += 14
        elif 14 <= dte < 21 or 60 < dte <= 90:
            score += 2
    elif style == "position":
        if 45 <= dte <= 120:
            score += 12
        elif 30 <= dte < 45 or 120 < dte <= 180:
            score += 2

    # IV is contextual, not inherently bad; only penalize unusually extreme
    # levels here so the selector does not blindly chase very expensive premium.
    if iv >= 150:
        score -= 8
    elif iv >= 100:
        score -= 3

    score = max(0.0, min(100.0, score))
    metrics = {
        "spread_pct": round(spread_pct, 2) if spread_pct is not None else None,
        "estimated_cost": round(cost, 2),
        "delta": round(delta, 4) if delta else None,
        "volume": int(volume),
        "open_interest": int(oi),
        "days_to_expiration": int(dte),
        "iv": round(iv, 2),
    }
    return round(score, 1), metrics


def rank_option_candidates(
    chain: dict[str, Any],
    *,
    direction: str,
    max_contract_cost: float = 300.0,
    style: str = "auto",
    limit: int = 3,
) -> list[dict[str, Any]]:
    rows = flatten_chain(chain, direction)
    output: list[dict[str, Any]] = []
    expected_type = "CALL" if str(direction).upper() == "LONG" else "PUT"
    style_name = str(style or "auto").lower()
    for contract in rows:
        contract_type = str(contract.get("putCall") or contract.get("contractType") or expected_type).upper()
        if contract_type != expected_type:
            continue
        ask = _number(contract.get("ask")) or 0.0
        if ask <= 0 or ask * 100.0 > float(max_contract_cost):
            continue
        eligible, _ = _style_eligible(contract, style_name)
        if not eligible:
            continue
        score, metrics = _fit_score(contract, style=style_name, max_contract_cost=float(max_contract_cost))
        output.append(
            {
                "symbol": contract.get("symbol"),
                "description": contract.get("description"),
                "contract_type": contract_type,
                "strike": _number(contract.get("strikePrice")),
                "expiration": _expiration_text(contract),
                "bid": _number(contract.get("bid")),
                "ask": ask,
                "mark": _number(contract.get("mark")),
                "last": _number(contract.get("last")),
                "score": score,
                "provider": "schwab",
                "style": style_name,
                "style_match": True,
                "in_the_money": contract.get("inTheMoney"),
                **metrics,
            }
        )
    output.sort(key=lambda row: (float(row.get("score") or 0.0), int(row.get("open_interest") or 0), int(row.get("volume") or 0)), reverse=True)
    return output[: max(1, int(limit))]
