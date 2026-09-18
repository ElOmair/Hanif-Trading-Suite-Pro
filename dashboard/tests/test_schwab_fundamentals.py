from schwab_fundamentals import score_equity_quote


def test_positive_earnings_reasonable_pe_and_strong_volume_score_healthy():
    result = score_equity_quote(
        "NVDA",
        {
            "assetMainType": "EQUITY",
            "fundamental": {
                "eps": 4.25,
                "peRatio": 28.0,
                "avg10DaysVolume": 60_000_000,
                "avg1YearVolume": 45_000_000,
                "divYield": 0.03,
                "lastEarningsDate": "2026-08-26T00:00:00Z",
            },
            "quote": {
                "lastPrice": 185.0,
                "52WeekHigh": 195.0,
                "52WeekLow": 95.0,
            },
        },
    )
    assert result["score"] is not None
    assert result["score"] >= 70
    assert result["coverage_pct"] == 100.0
    assert result["eps"] == 4.25
    assert result["pe_ratio"] == 28.0
    assert result["volume_ratio"] > 1.0
    assert result["week_52_range_position_pct"] == 90.0


def test_negative_earnings_and_high_valuation_are_cautionary():
    result = score_equity_quote(
        "XYZ",
        {
            "fundamental": {
                "eps": -1.0,
                "peRatio": -15.0,
                "avg10DaysVolume": 500_000,
                "avg1YearVolume": 1_000_000,
            },
            "quote": {"lastPrice": 20.0, "52WeekHigh": 60.0, "52WeekLow": 10.0},
        },
    )
    assert result["score"] is not None
    assert result["score"] < 55
    assert result["label"] in {"MIXED", "CAUTION"}


def test_missing_fields_reduce_coverage_instead_of_becoming_zeroes():
    result = score_equity_quote("ABC", {"fundamental": {"eps": 2.0}})
    assert result["score"] == 78.0
    assert result["coverage_pct"] == 35.0
    assert any(check["score"] is None for check in result["checks"])
