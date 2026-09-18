from __future__ import annotations

from typing import Any

MARKET_CORE = ["SPY", "QQQ"]
MAG7 = ["AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "TSLA"]

SECTOR_NAMES = {
    "XLK": "Technology",
    "XLC": "Communication Services",
    "XLY": "Consumer Discretionary",
    "XLF": "Financials",
    "XLE": "Energy",
    "XLV": "Healthcare",
    "XLI": "Industrials",
    "XLP": "Consumer Staples",
    "XLU": "Utilities",
    "XLB": "Materials",
    "XLRE": "Real Estate",
    "SMH": "Semiconductors",
}

# Deliberately biased toward liquid names with usable options. This is a focused
# experiment, not an exhaustive equity screener. The universe can be expanded
# later after the missed-trade detector tells us where coverage is weak.
SECTOR_MEMBERS = {
    "SMH": ["NVDA", "AMD", "AVGO", "MU", "ARM", "MRVL", "INTC", "QCOM", "SMCI", "NVTS"],
    "XLK": ["MSFT", "AAPL", "CRM", "ORCL", "PLTR"],
    "XLC": ["META", "GOOGL", "NFLX"],
    "XLY": ["AMZN", "TSLA", "UBER"],
    "XLF": ["JPM", "BAC", "GS", "SOFI"],
    "XLE": ["XOM", "CVX"],
    "XLV": ["LLY", "UNH"],
    "XLP": ["WMT", "COST"],
    "XLI": [],
    "XLU": [],
    "XLB": [],
    "XLRE": [],
}


def _number(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed == parsed else default


def sector_strength(snapshot: dict[str, Any], spy_momentum: float = 0.0) -> float:
    """Signed sector strength: positive leaders, negative laggards."""
    score = _number(snapshot.get("score"), 50.0)
    momentum = _number(snapshot.get("momentum_30m_pct"))
    rvol = _number(snapshot.get("rvol"), 1.0)
    relative = momentum - float(spy_momentum)
    raw = (score - 50.0) * 1.2 + momentum * 10.0 + relative * 8.0
    if momentum > 0:
        raw += max(0.0, rvol - 1.0) * 4.0
    elif momentum < 0:
        raw -= max(0.0, rvol - 1.0) * 4.0
    return round(max(-100.0, min(100.0, raw)), 1)


def rank_sectors(snapshots: list[dict[str, Any]], *, spy_momentum: float = 0.0) -> list[dict[str, Any]]:
    ranked: list[dict[str, Any]] = []
    for item in snapshots:
        symbol = str(item.get("symbol") or "").upper()
        if symbol not in SECTOR_NAMES:
            continue
        row = dict(item)
        row["sector"] = SECTOR_NAMES[symbol]
        row["relative_30m_pct"] = round(_number(item.get("momentum_30m_pct")) - float(spy_momentum), 2)
        row["strength"] = sector_strength(item, spy_momentum)
        ranked.append(row)
    return sorted(ranked, key=lambda row: _number(row.get("strength")), reverse=True)


def selected_sector_etfs(ranked: list[dict[str, Any]], *, leaders: int = 2, laggards: int = 1) -> list[str]:
    if not ranked:
        return []
    leader_rows = [row for row in ranked if _number(row.get("strength")) > 0][: max(0, leaders)]
    laggard_rows = [row for row in reversed(ranked) if _number(row.get("strength")) < 0][: max(0, laggards)]
    # In a very flat market we still return the relative top/bottom groups so the
    # UI can show that leadership is weak rather than pretending sectors vanished.
    if not leader_rows:
        leader_rows = ranked[: max(0, leaders)]
    if not laggard_rows:
        laggard_rows = list(reversed(ranked))[: max(0, laggards)]
    output: list[str] = []
    for row in leader_rows + laggard_rows:
        symbol = str(row.get("symbol") or "").upper()
        if symbol and symbol not in output:
            output.append(symbol)
    return output


def mover_priority(snapshot: dict[str, Any], sector_strength_value: float = 0.0) -> float:
    direction = str(snapshot.get("direction") or "NEUTRAL").upper()
    rank_score = _number(snapshot.get("rank_score"))
    momentum = abs(_number(snapshot.get("momentum_30m_pct")))
    rvol = _number(snapshot.get("rvol"), 1.0)
    aligned = (direction == "LONG" and sector_strength_value >= 0) or (direction == "SHORT" and sector_strength_value <= 0)
    return round(rank_score + min(12.0, momentum * 2.5) + min(10.0, max(0.0, rvol - 1.0) * 5.0) + (8.0 if aligned else 0.0), 1)


def rank_movers(
    snapshots: list[dict[str, Any]],
    *,
    sector_by_symbol: dict[str, str],
    sector_strength_by_etf: dict[str, float],
) -> list[dict[str, Any]]:
    ranked: list[dict[str, Any]] = []
    for item in snapshots:
        symbol = str(item.get("symbol") or "").upper()
        sector_etf = sector_by_symbol.get(symbol)
        if not sector_etf:
            continue
        row = dict(item)
        row["sector_etf"] = sector_etf
        row["sector"] = SECTOR_NAMES.get(sector_etf, sector_etf)
        row["sector_strength"] = _number(sector_strength_by_etf.get(sector_etf))
        row["focus_score"] = mover_priority(row, row["sector_strength"])
        row["sector_aligned"] = (
            (str(row.get("direction") or "").upper() == "LONG" and row["sector_strength"] >= 0)
            or (str(row.get("direction") or "").upper() == "SHORT" and row["sector_strength"] <= 0)
        )
        ranked.append(row)
    return sorted(ranked, key=lambda row: _number(row.get("focus_score")), reverse=True)


def _append_unique(output: list[dict[str, Any]], symbol: str, lane: str, reason: str, metadata: dict[str, Any] | None = None) -> None:
    symbol = str(symbol or "").upper()
    if not symbol or any(item["symbol"] == symbol for item in output):
        return
    row = {"symbol": symbol, "lane": lane, "reason": reason}
    if metadata:
        row.update(metadata)
    output.append(row)


def build_priority_queue(
    *,
    mag7_snapshots: list[dict[str, Any]],
    movers: list[dict[str, Any]],
    max_items: int = 8,
    mag7_slots: int = 2,
    mover_slots: int = 4,
) -> list[dict[str, Any]]:
    """Dynamic deep-review candidates; manual/sticky priorities are added by worker."""
    output: list[dict[str, Any]] = []
    for symbol in MARKET_CORE:
        _append_unique(output, symbol, "CORE", "Market context is always reviewed")

    mag7_ranked = sorted(
        (row for row in mag7_snapshots if str(row.get("symbol") or "").upper() in MAG7),
        key=lambda row: mover_priority(row, 0.0),
        reverse=True,
    )
    for row in mag7_ranked[: max(0, mag7_slots)]:
        symbol = str(row.get("symbol") or "").upper()
        _append_unique(
            output,
            symbol,
            "MAG7",
            "Most active Mag-7 name right now",
            {"direction": row.get("direction"), "score": row.get("score"), "rvol": row.get("rvol")},
        )

    # Preserve both directions when possible: strongest aligned longs and shorts
    # first, then fill with the remaining highest focus scores.
    longs = [row for row in movers if str(row.get("direction") or "").upper() == "LONG" and row.get("sector_aligned")]
    shorts = [row for row in movers if str(row.get("direction") or "").upper() == "SHORT" and row.get("sector_aligned")]
    balanced: list[dict[str, Any]] = []
    if longs:
        balanced.append(longs[0])
    if shorts:
        balanced.append(shorts[0])
    for row in movers:
        if row not in balanced:
            balanced.append(row)

    for row in balanced[: max(0, mover_slots)]:
        symbol = str(row.get("symbol") or "").upper()
        direction = str(row.get("direction") or "NEUTRAL").upper()
        sector = str(row.get("sector") or row.get("sector_etf") or "sector")
        _append_unique(
            output,
            symbol,
            "SECTOR_MOVER",
            f"{direction} mover aligned with {sector}",
            {
                "direction": direction,
                "sector": sector,
                "sector_etf": row.get("sector_etf"),
                "score": row.get("score"),
                "rvol": row.get("rvol"),
                "focus_score": row.get("focus_score"),
            },
        )

    return output[: max(1, int(max_items))]
