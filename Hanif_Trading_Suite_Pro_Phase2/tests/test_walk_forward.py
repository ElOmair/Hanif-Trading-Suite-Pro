import pandas as pd
import pytest

from walk_forward import build_walk_forward_folds


def sample_data(days=60):
    index = pd.date_range("2026-01-01", periods=days, freq="D")
    return pd.DataFrame({"Close": range(days)}, index=index)


def test_builds_four_non_overlapping_test_folds():
    folds = build_walk_forward_folds(
        sample_data(),
        initial_train_days=20,
        test_days=10,
    )

    assert len(folds) == 4
    test_days = []
    for train, test in folds:
        assert train.index.max() < test.index.min()
        assert len(test.index.normalize().unique()) == 10
        test_days.extend(test.index.normalize().tolist())

    assert len(test_days) == len(set(test_days))


def test_training_window_expands_between_folds():
    folds = build_walk_forward_folds(
        sample_data(),
        initial_train_days=20,
        test_days=10,
    )

    training_sizes = [len(train.index.normalize().unique()) for train, _ in folds]
    assert training_sizes == [20, 30, 40, 50]


def test_rejects_insufficient_history():
    with pytest.raises(ValueError, match="Not enough trading days"):
        build_walk_forward_folds(
            sample_data(25),
            initial_train_days=20,
            test_days=10,
        )
