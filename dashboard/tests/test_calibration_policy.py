from calibration_policy import build_calibration_policy


def test_policy_stays_shadow_when_sample_is_small():
    summary = {
        "evaluated_count": 12,
        "score_buckets": {
            "60-69": {"wins": 3, "losses": 3},
            "70-79": {"wins": 4, "losses": 2},
        },
    }
    policy = build_calibration_policy(summary, current_min_score=62, min_resolved_samples=30)
    assert policy["status"] == "SHADOW_LEARNING"
    assert policy["shadow_mode"] is True
    assert policy["recommended"]["min_score"] == 62.0
    assert policy["resolved_count"] == 12


def test_policy_recommends_lowest_threshold_that_meets_target():
    summary = {
        "evaluated_count": 50,
        "score_buckets": {
            "50-59": {"wins": 3, "losses": 7},
            "60-69": {"wins": 7, "losses": 8},
            "70-79": {"wins": 12, "losses": 6},
            "80-89": {"wins": 6, "losses": 1},
        },
    }
    policy = build_calibration_policy(
        summary,
        current_min_score=62,
        min_resolved_samples=30,
        target_win_rate_pct=60,
    )
    assert policy["status"] == "READY_FOR_REVIEW"
    assert policy["recommended"]["min_score"] == 70.0
    chosen = next(item for item in policy["candidates"] if item["threshold"] == 70.0)
    assert chosen["resolved"] == 25
    assert chosen["win_rate_pct"] == 72.0


def test_policy_never_relaxes_below_current_gate():
    summary = {
        "evaluated_count": 40,
        "score_buckets": {
            "50-59": {"wins": 12, "losses": 4},
            "60-69": {"wins": 10, "losses": 4},
            "70-79": {"wins": 7, "losses": 3},
        },
    }
    policy = build_calibration_policy(
        summary,
        current_min_score=68,
        min_resolved_samples=30,
        target_win_rate_pct=55,
    )
    assert policy["recommended"]["min_score"] >= 68.0


def test_policy_keeps_current_when_no_threshold_is_good_enough():
    summary = {
        "evaluated_count": 40,
        "score_buckets": {
            "60-69": {"wins": 8, "losses": 12},
            "70-79": {"wins": 6, "losses": 8},
            "80-89": {"wins": 2, "losses": 4},
        },
    }
    policy = build_calibration_policy(
        summary,
        current_min_score=62,
        min_resolved_samples=30,
        target_win_rate_pct=60,
    )
    assert policy["status"] == "KEEP_CURRENT"
    assert policy["recommended"]["min_score"] == 62.0
