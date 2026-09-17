from __future__ import annotations

import argparse
import json
import os

from calibration_policy import build_calibration_policy
from layer_calibration import summarize_layer_effectiveness
from option_shadow_store import option_mark_summary
from shadow_trade_store import shadow_trade_summary
from signal_store import calibration_summary, list_signals
from weight_challenger import walk_forward_weight_challenge


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def build_report(symbol: str | None = None, limit: int = 1000) -> dict:
    summary = calibration_summary(symbol=symbol, limit=limit)
    policy = build_calibration_policy(
        summary,
        current_min_score=_env_float("MNT_MIN_REVIEW_SCORE", 62.0),
        current_min_coverage=_env_float("MNT_MIN_REVIEW_COVERAGE", 55.0),
        min_resolved_samples=_env_int("MNT_CALIBRATION_MIN_RESOLVED", 30),
        target_win_rate_pct=_env_float("MNT_CALIBRATION_TARGET_WIN_RATE", 55.0),
    )
    history = list_signals(symbol=symbol, limit=limit)
    layers = summarize_layer_effectiveness(
        history,
        supportive_score=_env_float("MNT_LAYER_SUPPORTIVE_SCORE", 60.0),
        min_samples=_env_int("MNT_LAYER_MIN_SAMPLES", 10),
    )
    weight_challenge = walk_forward_weight_challenge(
        history,
        train_fraction=_env_float("MNT_WEIGHT_CHALLENGER_TRAIN_FRACTION", 0.70),
        min_resolved=_env_int("MNT_WEIGHT_CHALLENGER_MIN_RESOLVED", 40),
        min_holdout=_env_int("MNT_WEIGHT_CHALLENGER_MIN_HOLDOUT", 12),
        min_candidate_selected=_env_int("MNT_WEIGHT_CHALLENGER_MIN_SELECTED", 8),
        min_score=_env_float("MNT_MIN_REVIEW_SCORE", 62.0),
        min_coverage_pct=_env_float("MNT_MIN_REVIEW_COVERAGE", 55.0),
        min_layer_lift_pct_points=_env_float("MNT_WEIGHT_CHALLENGER_MIN_LAYER_LIFT", 8.0),
        min_holdout_improvement_pct_points=_env_float("MNT_WEIGHT_CHALLENGER_MIN_HOLDOUT_IMPROVEMENT", 3.0),
    )
    shadow = shadow_trade_summary(symbol=symbol, limit=limit)
    option_returns = option_mark_summary(
        symbol=symbol,
        max_lag_minutes=_env_float("MNT_OPTION_MARK_MAX_LAG_MINUTES", 10.0),
        limit=max(limit * 4, 1000),
    )
    return {
        "summary": summary,
        "policy": policy,
        "layer_effectiveness": layers,
        "weight_challenge": weight_challenge,
        "ready_alert_shadow_trades": shadow,
        "option_contract_shadow_returns": option_returns,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Print MnT outcome calibration, shadow threshold recommendations, "
            "layer effectiveness, chronological weight challenges, READY-alert shadow results, "
            "and actual option-contract quote returns."
        )
    )
    parser.add_argument("--symbol", help="Optional ticker to calibrate separately, e.g. SPY")
    parser.add_argument("--limit", type=int, default=1000, help="Maximum historical signals to inspect")
    args = parser.parse_args()
    symbol = args.symbol.strip().upper() if args.symbol else None
    print(json.dumps(build_report(symbol=symbol, limit=max(1, min(5000, args.limit))), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
