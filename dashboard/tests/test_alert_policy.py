from alert_policy import build_discord_message, build_stand_down_message, classify_alert


def _base_payload():
    return {
        "symbol": "SPY",
        "technical": {"signal": "LONG", "price": 760, "entry_low": 759, "entry_high": 760, "atr": 1.0},
        "fusion_score": {"direction": "LONG", "score": 78, "coverage_pct": 75},
        "decision": {"decision": "WATCH"},
        "execution_gate": {
            "state": "WAIT",
            "entry_review_allowed": False,
            "no_chase": {"blocked": False, "limit": 760.25},
        },
        "market_gate": {"active": False},
        "trade_plan": {"entry_low": 759, "entry_high": 760, "stop": 757.5, "tp1": 763},
        "gamma": {"available": True, "gamma_flip": 755.5, "call_wall": 765, "put_wall": 754},
        "flow": {"available": True, "sentiment": "BULLISH"},
        "options": [],
    }


def test_pretrigger_alert_happens_before_confirm():
    payload = _base_payload()
    result = classify_alert(payload, pretrigger_score=72, pretrigger_coverage=55)
    assert result["alert"] is True
    assert result["state"] == "PRE_TRIGGER"


def test_ready_alert_requires_server_gate():
    payload = _base_payload()
    payload["decision"] = {"decision": "CONFIRM"}
    payload["execution_gate"]["state"] = "REVIEW_ENTRY"
    payload["execution_gate"]["entry_review_allowed"] = True
    result = classify_alert(payload)
    assert result["alert"] is True
    assert result["state"] == "READY"


def test_no_chase_blocks_alert():
    payload = _base_payload()
    payload["decision"] = {"decision": "CONFIRM"}
    payload["execution_gate"]["no_chase"]["blocked"] = True
    result = classify_alert(payload)
    assert result["alert"] is False
    assert result["state"] == "NO_CHASE"
    assert "no-chase" in result["reason"]


def test_low_coverage_does_not_pretrigger():
    payload = _base_payload()
    payload["fusion_score"]["coverage_pct"] = 40
    result = classify_alert(payload, pretrigger_score=72, pretrigger_coverage=55)
    assert result["alert"] is False
    assert result["state"] == "WATCH"


def test_message_explains_pretrigger_and_no_chase_level():
    payload = _base_payload()
    classification = classify_alert(payload)
    message = build_discord_message(payload, classification)
    text = message["embeds"][0]["description"]
    assert "Do not buy yet" in text
    assert "Do not chase past" in text
    assert "Gamma" in text
    assert "Options flow" in text


def test_stand_down_message_cancels_pretrigger_not_existing_position():
    payload = _base_payload()
    payload["execution_gate"]["no_chase"]["blocked"] = True
    classification = classify_alert(payload)
    message = build_stand_down_message(payload, classification)
    text = message["embeds"][0]["description"]
    assert "Do not enter late" in text
    assert "cancels the earlier PRE-TRIGGER watch" in text
    assert "not an exit instruction" in text
    assert "STAND DOWN" in message["embeds"][0]["title"]
