from __future__ import annotations

from math import sqrt
from typing import Any, Iterable

LAYER_WEIGHTS = {
    "technical": 25.0,
    "kronos": 20.0,
    "gamma": 15.0,
    "flow": 15.0,
    "market": 10.0,
    "contract": 10.0,
    "momentum": 5.0,
}


def clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, float(value)))


def _number(value: Any) -> float | None:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if value == value else None


def _direction(value: Any) -> str:
    text = str(value or "").strip().upper()
    if text in {"LONG", "BULLISH", "CALL", "UP"}:
        return "LONG"
    if text in {"SHORT", "BEARISH", "PUT", "DOWN"}:
        return "SHORT"
    return "NEUTRAL"


def _aligned_text(value: Any, direction: str) -> bool:
    text = str(value or "").strip().lower()
    if direction == "LONG":
        return text in {"bullish", "long", "above", "positive", "up"}
    if direction == "SHORT":
        return text in {"bearish", "short", "below", "negative", "down"}
    return False


def _opposed_text(value: Any, direction: str) -> bool:
    text = str(value or "").strip().lower()
    if direction == "LONG":
        return text in {"bearish", "short", "below", "negative", "down"}
    if direction == "SHORT":
        return text in {"bullish", "long", "above", "positive", "up"}
    return False


def score_technical(technical: dict[str, Any] | None) -> dict[str, Any] | None:
    if not technical:
        return None
    direction = _direction(technical.get("signal") or technical.get("direction"))
    raw = _number(technical.get("technical_score_preview") or technical.get("score"))
    if direction == "NEUTRAL":
        return {"score": 45.0, "reason": "The short-term chart is mixed, so MnT does not have a clear directional edge."}
    if raw is None:
        raw = 50.0
    score = raw if direction == "LONG" else 100.0 - raw
    confirmations = 0
    conflicts = 0
    for key in ("bos", "choch", "vwap", "fvg", "orb"):
        value = technical.get(key)
        confirmations += int(_aligned_text(value, direction))
        conflicts += int(_opposed_text(value, direction))
    score += confirmations * 2.5 - conflicts * 2.5
    return {
        "score": round(clamp(score), 1),
        "reason": f"{confirmations} chart checks support the {direction.lower()} idea; {conflicts} push the other way.",
        "confirmations": confirmations,
        "conflicts": conflicts,
    }


def score_momentum(technical: dict[str, Any] | None) -> dict[str, Any] | None:
    if not technical:
        return None
    direction = _direction(technical.get("signal") or technical.get("direction"))
    if direction == "NEUTRAL":
        return {"score": 45.0, "reason": "Momentum is not directional enough yet."}
    rvol = _number(technical.get("rvol"))
    score = 55.0
    if rvol is not None:
        if rvol >= 2.0:
            score += 25
        elif rvol >= 1.5:
            score += 18
        elif rvol >= 1.1:
            score += 10
        elif rvol < 0.75:
            score -= 12
    if technical.get("volume") is True:
        score += 5
    return {
        "score": round(clamp(score), 1),
        "reason": "Trading activity is strong enough to help the move." if score >= 70 else "Volume is not giving the setup a large extra push yet.",
        "rvol": rvol,
    }


def score_kronos(kronos: dict[str, Any] | None, direction: str) -> dict[str, Any] | None:
    if not kronos:
        return None
    bias = _direction(kronos.get("final_bias"))
    agreement = _number(kronos.get("bias_agreement_pct"))
    path_count = int(_number(kronos.get("path_count")) or 0)
    matching_paths = _number(kronos.get("bullish_paths" if direction == "LONG" else "bearish_paths"))
    if agreement is None and path_count > 0 and matching_paths is not None:
        agreement = 100.0 * matching_paths / path_count
    agreement = 50.0 if agreement is None else clamp(agreement)
    score = 45.0 + (agreement - 50.0) * 0.7
    if bias == direction:
        score += 18
    elif bias != "NEUTRAL":
        score -= 22
    stability = str(kronos.get("stability") or "").upper()
    score += {"HIGH": 8, "MEDIUM": 3, "LOW": -5}.get(stability, 0)
    return {
        "score": round(clamp(score), 1),
        "reason": "Kronos agrees with the direction." if bias == direction else "Kronos does not fully agree with the chart direction.",
        "bias": bias,
        "agreement_pct": round(agreement, 1),
        "stability": stability or None,
    }


def score_gamma(gamma: dict[str, Any] | None, direction: str, spot: float | None = None) -> dict[str, Any] | None:
    if not gamma or gamma.get("available") is False:
        return None
    spot = _number(spot if spot is not None else gamma.get("spot"))
    flip = _number(gamma.get("gamma_flip"))
    call_wall = _number(gamma.get("call_wall"))
    put_wall = _number(gamma.get("put_wall"))
    regime = str(gamma.get("regime") or "").upper()
    score = 55.0
    notes: list[str] = []

    if "NEGATIVE" in regime or "EXPANSION" in regime:
        score += 12
        notes.append("Gamma conditions can help a directional move travel faster.")
    elif "POSITIVE" in regime or "PIN" in regime or "MEAN" in regime:
        score -= 8
        notes.append("Gamma conditions may slow price down or cause more back-and-forth movement.")

    if spot and flip:
        above = spot >= flip
        aligned = (direction == "LONG" and above) or (direction == "SHORT" and not above)
        score += 10 if aligned else -10
        notes.append("Price is on the supportive side of the gamma flip." if aligned else "Price is on the less favorable side of the gamma flip.")

    if spot and direction == "LONG" and call_wall and call_wall > spot:
        distance = (call_wall / spot - 1.0) * 100.0
        if distance < 0.45:
            score -= 12
            notes.append("A nearby call wall could slow the upside almost immediately.")
        elif distance <= 3.0:
            score += 4
            notes.append("The call wall gives MnT a useful upside reference level.")
    if spot and direction == "SHORT" and put_wall and put_wall < spot:
        distance = (1.0 - put_wall / spot) * 100.0
        if distance < 0.45:
            score -= 12
            notes.append("A nearby put wall could slow the downside almost immediately.")
        elif distance <= 3.0:
            score += 4
            notes.append("The put wall gives MnT a useful downside reference level.")

    return {
        "score": round(clamp(score), 1),
        "reason": " ".join(notes) or "Gamma levels are available but are not strongly helping or hurting this setup.",
        "regime": regime or None,
        "gamma_flip": flip,
        "call_wall": call_wall,
        "put_wall": put_wall,
    }


def score_sentiment_layer(layer: dict[str, Any] | None, direction: str, name: str) -> dict[str, Any] | None:
    if not layer or layer.get("available") is False:
        return None
    explicit = _number(layer.get("score"))
    sentiment = _direction(layer.get("sentiment") or layer.get("direction") or layer.get("bias"))
    if explicit is not None:
        score = explicit if sentiment in {"NEUTRAL", direction} else 100.0 - explicit
    elif sentiment == direction:
        score = 78.0
    elif sentiment == "NEUTRAL":
        score = 50.0
    else:
        score = 28.0
    reason = f"{name} supports the trade direction." if sentiment == direction else f"{name} is mixed or pushing against the trade direction."
    return {"score": round(clamp(score), 1), "reason": reason, "sentiment": sentiment}


def score_contract(options: Iterable[dict[str, Any]] | None) -> dict[str, Any] | None:
    options = list(options or [])
    if not options:
        return None
    candidate = options[0] or {}
    explicit = _number(candidate.get("score") or candidate.get("total_score") or candidate.get("fit_score"))
    score = 65.0 if explicit is None else explicit
    bid = _number(candidate.get("bid") or candidate.get("bid_price"))
    ask = _number(candidate.get("ask") or candidate.get("ask_price"))
    spread_pct = None
    if bid and ask and ask > 0 and ask >= bid:
        mid = (bid + ask) / 2.0
        spread_pct = (ask - bid) / mid * 100.0 if mid > 0 else None
        if spread_pct is not None:
            if spread_pct <= 5:
                score += 8
            elif spread_pct >= 15:
                score -= 16
            elif spread_pct >= 10:
                score -= 8
    return {
        "score": round(clamp(score), 1),
        "reason": "The selected option has a reasonable mechanical fit." if score >= 70 else "The option contract needs extra caution on price or liquidity.",
        "spread_pct": round(spread_pct, 2) if spread_pct is not None else None,
    }


def _grade(score: float, coverage: float) -> tuple[str, str]:
    if coverage < 45:
        return "LOW_DATA", "KEEP AN EYE ON THIS"
    if score >= 86 and coverage >= 65:
        return "STRONG", "GET READY"
    if score >= 76:
        return "GOOD", "WATCH CLOSELY"
    if score >= 62:
        return "MIXED", "WAIT FOR MORE PROOF"
    return "WEAK", "SKIP FOR NOW"


def build_fusion_score(
    *,
    technical: dict[str, Any] | None,
    kronos: dict[str, Any] | None = None,
    gamma: dict[str, Any] | None = None,
    flow: dict[str, Any] | None = None,
    market: dict[str, Any] | None = None,
    options: Iterable[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    direction = _direction((technical or {}).get("signal") or (technical or {}).get("direction"))
    spot = _number((technical or {}).get("price"))
    components = {
        "technical": score_technical(technical),
        "kronos": score_kronos(kronos, direction),
        "gamma": score_gamma(gamma, direction, spot),
        "flow": score_sentiment_layer(flow, direction, "Options flow"),
        "market": score_sentiment_layer(market, direction, "The overall market"),
        "contract": score_contract(options),
        "momentum": score_momentum(technical),
    }
    available_weight = sum(LAYER_WEIGHTS[name] for name, component in components.items() if component is not None)
    total_weight = sum(LAYER_WEIGHTS.values())
    if available_weight <= 0:
        score = 0.0
    else:
        score = sum(component["score"] * LAYER_WEIGHTS[name] for name, component in components.items() if component is not None) / available_weight
    coverage = 100.0 * available_weight / total_weight
    grade, beginner_state = _grade(score, coverage)
    return {
        "score": round(clamp(score), 1),
        "coverage_pct": round(coverage, 1),
        "available_weight": round(available_weight, 1),
        "total_weight": round(total_weight, 1),
        "direction": direction,
        "grade": grade,
        "beginner_state": beginner_state,
        "components": components,
        "missing_layers": [name for name, component in components.items() if component is None],
        "explanation": "MnT reweights only the data layers that are actually available. Missing Gamma/flow data does not count as a zero.",
    }


def _ema(values: list[float], span: int) -> float:
    alpha = 2.0 / (span + 1.0)
    result = values[0]
    for value in values[1:]:
        result = value * alpha + result * (1.0 - alpha)
    return result


def score_position_bars(rows: Iterable[dict[str, Any]]) -> dict[str, Any] | None:
    bars = list(rows)
    closes = [_number(row.get("close")) for row in bars]
    closes = [value for value in closes if value is not None]
    highs = [_number(row.get("high")) for row in bars]
    highs = [value for value in highs if value is not None]
    if len(closes) < 80 or len(highs) < 80:
        return None
    last = closes[-1]
    ema20 = _ema(closes[-120:], 20)
    ema50 = _ema(closes[-180:], 50)
    ema200 = _ema(closes[-260:], 200) if len(closes) >= 200 else None
    ret20 = (last / closes[-21] - 1.0) * 100.0
    ret60 = (last / closes[-61] - 1.0) * 100.0
    high252 = max(highs[-min(252, len(highs)):])
    from_high = (last / high252 - 1.0) * 100.0 if high252 else 0.0
    daily_returns = [closes[i] / closes[i - 1] - 1.0 for i in range(max(1, len(closes) - 21), len(closes))]
    mean = sum(daily_returns) / len(daily_returns)
    variance = sum((x - mean) ** 2 for x in daily_returns) / len(daily_returns)
    annual_vol = sqrt(variance) * sqrt(252.0) * 100.0

    score = 50.0
    score += 9 if last > ema20 else -7
    score += 10 if ema20 > ema50 else -6
    if ema200 is not None:
        score += 10 if ema50 > ema200 else -10
    score += clamp(ret20 * 0.45, -9, 9)
    score += clamp(ret60 * 0.32, -13, 13)
    if -12 <= from_high <= -2 and last > ema50:
        score += 4
    if from_high < -20:
        score -= 7
    score = clamp(score)

    return {
        "score": round(score, 1),
        "price": round(last, 4),
        "ret20_pct": round(ret20, 2),
        "ret60_pct": round(ret60, 2),
        "from_high_pct": round(from_high, 2),
        "annualized_vol_pct": round(annual_vol, 2),
        "ema20": round(ema20, 4),
        "ema50": round(ema50, 4),
        "ema200": round(ema200, 4) if ema200 is not None else None,
        "risk": "LOWER" if annual_vol < 30 else "MEDIUM" if annual_vol < 50 else "HIGHER",
        "trend": "UPTREND" if last > ema20 > ema50 else "IMPROVING" if last > ema50 else "WEAK",
        "watch_low": round(min(last, ema20) * 0.985, 4),
        "watch_high": round(max(last, ema20) * 1.01, 4),
        "research_only": True,
    }
