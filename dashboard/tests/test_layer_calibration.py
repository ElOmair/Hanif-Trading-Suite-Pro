from layer_calibration import summarize_layer_effectiveness


def _row(label, technical=None, gamma=None):
    return {
        "outcome": {"calibration_label": label},
        "payload": {
            "fusion_score": {
                "components": {
                    "technical": None if technical is None else {"score": technical},
                    "gamma": None if gamma is None else {"score": gamma},
                }
            }
        },
    }


def test_layer_summary_measures_supportive_lift():
    rows = []
    rows += [_row("WIN", technical=80, gamma=70) for _ in range(8)]
    rows += [_row("LOSS", technical=80, gamma=70) for _ in range(2)]
    rows += [_row("WIN", technical=45, gamma=40) for _ in range(3)]
    rows += [_row("LOSS", technical=45, gamma=40) for _ in range(7)]

    report = summarize_layer_effectiveness(rows, supportive_score=60, min_samples=5)
    technical = report["layers"]["technical"]
    assert report["resolved_count"] == 20
    assert technical["supportive_win_rate_pct"] == 80.0
    assert technical["below_supportive_win_rate_pct"] == 30.0
    assert technical["supportive_vs_weak_lift_pct_points"] == 50.0
    assert technical["enough_samples"] is True


def test_missing_component_is_measured_separately():
    rows = [
        _row("WIN", technical=80, gamma=None),
        _row("LOSS", technical=70, gamma=None),
        _row("WIN", technical=85, gamma=75),
        _row("WIN", technical=90, gamma=80),
    ]
    report = summarize_layer_effectiveness(rows, min_samples=1)
    gamma = report["layers"]["gamma"]
    assert gamma["present_count"] == 2
    assert gamma["missing_count"] == 2
    assert gamma["present_win_rate_pct"] == 100.0
    assert gamma["missing_win_rate_pct"] == 50.0


def test_ambiguous_and_unresolved_rows_are_excluded():
    rows = [
        _row("WIN", technical=80),
        _row("LOSS", technical=40),
        _row("AMBIGUOUS", technical=90),
        _row("UNRESOLVED", technical=90),
    ]
    report = summarize_layer_effectiveness(rows, min_samples=1)
    assert report["resolved_count"] == 2
    assert report["overall_target_first_win_rate_pct"] == 50.0
