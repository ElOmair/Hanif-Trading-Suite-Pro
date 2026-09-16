from __future__ import annotations

from gamma_provider import derive_oi_gex_levels


def test_derive_oi_gex_levels_finds_walls_flip_and_regime() -> None:
    rows = [
        {"strike": "95", "call_gex": "20", "put_gex": "-5"},
        {"strike": "98", "call_gex": "2", "put_gex": "-10"},
        {"strike": "100", "call_gex": "4", "put_gex": "-7"},
        {"strike": "102", "call_gex": "18", "put_gex": "-3"},
        {"strike": "105", "call_gex": "40", "put_gex": "-5"},
    ]
    result = derive_oi_gex_levels(rows, 100.0)
    assert result["available"] is True
    assert result["call_wall"] == 105.0
    assert result["put_wall"] == 95.0
    assert result["gamma_flip"] is not None
    assert result["gamma_magnet"] == 105.0
    assert result["regime"] in {"POSITIVE_GAMMA_PIN", "NEGATIVE_GAMMA_EXPANSION"}
    assert result["basis"] == "open_interest"


def test_empty_gamma_profile_is_explicitly_unavailable() -> None:
    result = derive_oi_gex_levels([], 100.0)
    assert result["available"] is False
    assert result["status"] == "empty_profile"
