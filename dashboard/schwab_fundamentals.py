from __future__ import annotations

from typing import Any


def _number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result == result else None


def _get(mapping: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in mapping and mapping[key] not in (None, ""):
            return mapping[key]
    return None


def score_equity_quote(symbol: str, quote_payload: dict[str, Any] | None) -> dict[str, Any]:
    root = quote_payload or {}
    fundamental = root.get("fundamental") or root.get("fundamentals") or {}
    quote = root.get("quote") or root.get("regular") or {}
    reference = root.get("reference") or {}

    eps = _number(_get(fundamental, "eps", "EPS"))
    pe = _number(_get(fundamental, "peRatio", "PERatio", "pe_ratio"))
    div_yield = _number(_get(fundamental, "divYield", "dividendYield", "div_yield"))
    avg10 = _number(_get(fundamental, "avg10DaysVolume", "avg10DayVolume", "avg_10_days_volume"))
    avg1y = _number(_get(fundamental, "avg1YearVolume", "avg_1_year_volume"))
    last_earnings = _get(fundamental, "lastEarningsDate", "last_earnings_date")

    last = _number(_get(quote, "lastPrice", "mark", "closePrice"))
    high52 = _number(_get(quote, "52WeekHigh", "fiftyTwoWeekHigh"))
    low52 = _number(_get(quote, "52WeekLow", "fiftyTwoWeekLow"))
    asset_type = _get(root, "assetMainType", "assetType") or _get(reference, "assetMainType", "assetType")

    checks: list[dict[str, Any]] = []
    weighted_sum = 0.0
    available_weight = 0.0

    def add(name: str, score: float | None, weight: float, explanation: str) -> None:
        nonlocal weighted_sum, available_weight
        checks.append({"name": name, "score": round(score, 1) if score is not None else None, "weight": weight, "explanation": explanation})
        if score is not None:
            weighted_sum += score * weight
            available_weight += weight

    if eps is None:
        add("earnings", None, 35, "Schwab did not return EPS for this symbol.")
    elif eps > 0:
        add("earnings", 78, 35, "The company is currently reporting positive earnings per share.")
    elif eps == 0:
        add("earnings", 45, 35, "Reported earnings per share are around break-even.")
    else:
        add("earnings", 25, 35, "Reported earnings per share are negative, which raises business-risk for a multi-month hold.")

    if pe is None or pe == 0:
        add("valuation", None, 25, "P/E is unavailable or not meaningful for this quote.")
    elif pe < 0:
        add("valuation", 30, 25, "P/E is negative, usually because trailing earnings are negative.")
    elif pe <= 15:
        add("valuation", 82, 25, "The trailing P/E is relatively low; MnT treats that as valuation support, not a guarantee of value.")
    elif pe <= 30:
        add("valuation", 72, 25, "The trailing P/E is moderate enough that valuation is not an obvious warning by itself.")
    elif pe <= 50:
        add("valuation", 58, 25, "The stock carries a richer trailing P/E, so future growth needs to justify the price.")
    else:
        add("valuation", 42, 25, "The trailing P/E is high; MnT flags valuation risk for a multi-month hold.")

    volume_ratio = (avg10 / avg1y) if avg10 and avg1y and avg1y > 0 else None
    if volume_ratio is None:
        add("participation", None, 15, "Average-volume comparison is unavailable.")
    elif volume_ratio >= 1.35:
        add("participation", 84, 15, "Recent average trading activity is well above the one-year norm.")
    elif volume_ratio >= 1.0:
        add("participation", 70, 15, "Recent average trading activity is at or above the one-year norm.")
    elif volume_ratio >= 0.7:
        add("participation", 55, 15, "Recent trading activity is somewhat below the one-year norm.")
    else:
        add("participation", 38, 15, "Recent trading activity is unusually light versus the one-year norm.")

    range_position = None
    if last is not None and high52 is not None and low52 is not None and high52 > low52:
        range_position = (last - low52) / (high52 - low52)
        range_score = 45 + max(0.0, min(1.0, range_position)) * 40
        add("52_week_position", range_score, 25, "Price location inside the 52-week range is used as a simple longer-term strength check.")
    else:
        add("52_week_position", None, 25, "52-week price-range context is unavailable.")

    score = (weighted_sum / available_weight) if available_weight else None
    coverage = available_weight / 100.0 * 100.0

    if score is None:
        label = "NO_DATA"
    elif score >= 78:
        label = "STRONG"
    elif score >= 65:
        label = "HEALTHY"
    elif score >= 52:
        label = "MIXED"
    else:
        label = "CAUTION"

    return {
        "symbol": str(symbol or "").upper(),
        "asset_type": asset_type,
        "score": round(score, 1) if score is not None else None,
        "coverage_pct": round(coverage, 1),
        "label": label,
        "eps": eps,
        "pe_ratio": pe,
        "dividend_yield": div_yield,
        "avg_10_day_volume": avg10,
        "avg_1_year_volume": avg1y,
        "volume_ratio": round(volume_ratio, 2) if volume_ratio is not None else None,
        "last_earnings_date": last_earnings,
        "last_price": last,
        "week_52_high": high52,
        "week_52_low": low52,
        "week_52_range_position_pct": round(range_position * 100.0, 1) if range_position is not None else None,
        "checks": checks,
        "note": "Schwab quote fundamentals are a screening layer, not a full financial-statement or forward-estimate model.",
    }
