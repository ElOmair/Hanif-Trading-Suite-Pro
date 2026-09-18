from score_discrimination import summarize_score_discrimination


def _row(score: float, label: str):
    return {"score": score, "outcome": {"calibration_label": label}}


def test_strong_score_ranking_has_high_auc_and_band_separation():
    rows = []
    for score in range(50, 70):
        rows.append(_row(score, "LOSS"))
    for score in range(80, 100):
        rows.append(_row(score, "WIN"))
    report = summarize_score_discrimination(rows, minimum_resolved=30, band_fraction=0.25)
    assert report["resolved"] == 40
    assert report["roc_auc"] == 1.0
    assert report["top_score_band"]["win_rate_pct"] == 100.0
    assert report["bottom_score_band"]["win_rate_pct"] == 0.0
    assert report["top_minus_bottom_win_rate_pct_points"] == 100.0
    assert report["state"] == "STRONG"


def test_tied_scores_receive_half_credit_in_auc():
    rows = [_row(70, "WIN"), _row(70, "LOSS"), _row(80, "WIN"), _row(60, "LOSS")]
    report = summarize_score_discrimination(rows, minimum_resolved=4, band_fraction=0.25)
    assert report["roc_auc"] == 0.875


def test_small_sample_stays_collecting_even_if_perfect():
    rows = [_row(90 + i, "WIN") for i in range(5)] + [_row(50 + i, "LOSS") for i in range(5)]
    report = summarize_score_discrimination(rows, minimum_resolved=30)
    assert report["roc_auc"] == 1.0
    assert report["state"] == "COLLECTING"


def test_ambiguous_and_pending_rows_are_ignored():
    rows = [
        _row(90, "WIN"),
        _row(50, "LOSS"),
        _row(99, "AMBIGUOUS"),
        {"score": 88, "outcome": {}},
    ]
    report = summarize_score_discrimination(rows, minimum_resolved=2)
    assert report["resolved"] == 2
    assert report["roc_auc"] == 1.0
    assert report["overall_wilson_95_low_pct"] is not None
    assert report["overall_wilson_95_high_pct"] is not None


def test_score_can_be_read_from_fusion_payload_when_direct_field_missing():
    rows = [
        {"payload": {"fusion_score": {"score": 90}}, "outcome": {"calibration_label": "WIN"}},
        {"payload": {"fusion_score": {"score": 50}}, "outcome": {"calibration_label": "LOSS"}},
    ]
    report = summarize_score_discrimination(rows, minimum_resolved=2)
    assert report["roc_auc"] == 1.0
