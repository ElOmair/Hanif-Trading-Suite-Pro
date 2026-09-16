from __future__ import annotations

from flow_provider import summarize_flow_rows


def test_bullish_flow_is_detected_from_premium() -> None:
    result = summarize_flow_rows(
        [
            {"bullish_premium": "900000", "bearish_premium": "300000", "transactions": 80, "call_volume": 1000, "put_volume": 600},
        ]
    )
    assert result["available"] is True
    assert result["sentiment"] == "BULLISH"
    assert result["score"] > 65


def test_bearish_flow_is_detected_from_interval_net_premium() -> None:
    result = summarize_flow_rows(
        [
            {"net_call_prem": "-100000", "net_put_prem": "500000", "dir_delta_flow": "-120000", "transactions": 40, "volume": 900},
        ]
    )
    assert result["available"] is True
    assert result["sentiment"] == "BEARISH"
    assert result["directional_ratio"] < 0


def test_empty_flow_is_not_faked() -> None:
    result = summarize_flow_rows([])
    assert result["available"] is False
    assert result["status"] == "empty_flow"
