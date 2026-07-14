import pandas as pd
import pytest

from validation import select_configuration, split_chronologically


def sample_data(days=10):
    index = pd.date_range("2026-01-01", periods=days, freq="D")
    return pd.DataFrame({"Close": range(days)}, index=index)


def test_split_is_chronological_and_keeps_test_unseen():
    train, test, cutoff = split_chronologically(sample_data(), 0.70)

    assert len(train) == 7
    assert len(test) == 3
    assert train.index.max() == cutoff
    assert train.index.max() < test.index.min()


def test_split_rejects_too_little_history():
    with pytest.raises(ValueError, match="10 trading days"):
        split_chronologically(sample_data(9), 0.70)


def test_select_configuration_ignores_tiny_trade_samples():
    sweep = pd.DataFrame([
        {
            "minimum_score": 90, "minimum_adx": 30, "minimum_rvol": 1.5,
            "stop_atr": 1.5, "target_r": 2.5, "allow_long": True,
            "allow_short": False, "trades": 3, "rank_score": 500,
        },
        {
            "minimum_score": 75, "minimum_adx": 25, "minimum_rvol": 1.2,
            "stop_atr": 1.5, "target_r": 1.5, "allow_long": True,
            "allow_short": False, "trades": 20, "rank_score": 200,
        },
    ])

    selected = select_configuration(sweep, minimum_trades=10)

    assert selected["minimum_score"] == 75
    assert selected["minimum_adx"] == 25
    assert selected["allow_short"] is False
