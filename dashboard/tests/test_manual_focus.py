import asyncio

import mnt_alert_worker as worker
from manual_focus import focus_symbols, list_focus_items, remove_focus_item, upsert_focus_item


def test_manual_focus_persists_and_prioritizes_open_positions(monkeypatch, tmp_path):
    path = tmp_path / "focus.json"
    monkeypatch.setenv("MNT_MANUAL_FOCUS_FILE", str(path))
    monkeypatch.setenv("MNT_MANUAL_FOCUS_MAX", "8")

    upsert_focus_item(symbol="AMD", kind="WATCHING", note="sector mover")
    upsert_focus_item(symbol="TSLA", kind="OPEN_OPTION", direction="LONG", entry_price=2.15, contract="TSLA 261016C00400000")
    upsert_focus_item(symbol="NVDA", kind="OPEN_STOCK", direction="LONG", entry_price=185.0, shares=4)

    items = list_focus_items()
    assert [item["symbol"] for item in items] == ["TSLA", "NVDA", "AMD"]
    assert focus_symbols(limit=2) == ["TSLA", "NVDA"]
    assert next(item for item in items if item["symbol"] == "NVDA")["shares"] == 4
    assert path.exists()

    upsert_focus_item(symbol="AMD", kind="OPEN_STOCK", direction="LONG", entry_price=210.0, shares=1.5)
    assert [item["symbol"] for item in list_focus_items()][0] == "AMD"
    assert next(item for item in list_focus_items() if item["symbol"] == "AMD")["shares"] == 1.5
    assert remove_focus_item("NVDA") is True
    assert remove_focus_item("NVDA") is False


def test_manual_focus_rejects_invalid_values(monkeypatch, tmp_path):
    monkeypatch.setenv("MNT_MANUAL_FOCUS_FILE", str(tmp_path / "focus.json"))
    try:
        upsert_focus_item(symbol="BAD SYMBOL")
        assert False, "invalid symbol should fail"
    except ValueError:
        pass

    try:
        upsert_focus_item(symbol="SPY", kind="UNKNOWN")
        assert False, "invalid kind should fail"
    except ValueError:
        pass

    try:
        upsert_focus_item(symbol="NVDA", kind="OPEN_STOCK", entry_price=185.0)
        assert False, "open stock should require share quantity"
    except ValueError:
        pass


def test_alert_scan_reserves_manual_focus_slots(monkeypatch, tmp_path):
    monkeypatch.setenv("MNT_FUSION_SHORTLIST", "6")
    monkeypatch.setenv("MNT_MANUAL_FOCUS_SLOTS", "4")
    monkeypatch.setenv("MNT_STICKY_PRETRIGGER_LIMIT", "0")
    monkeypatch.delenv("MNT_DISCORD_WEBHOOK_URL", raising=False)

    monkeypatch.setattr(worker, "_symbols", lambda: ["SPY", "QQQ", "NVDA", "TSLA", "AMD"])
    monkeypatch.setattr(worker, "list_focus_items", lambda: [
        {"symbol": "SMCI", "kind": "OPEN_OPTION"},
        {"symbol": "ARM", "kind": "OPEN_STOCK"},
        {"symbol": "MU", "kind": "WATCHING"},
        {"symbol": "AVGO", "kind": "WATCHING"},
    ])

    async def fake_radar(client, base_url, limit=20):
        return {
            "longs": [
                {"symbol": "NVDA", "rank_score": 95},
                {"symbol": "SPY", "rank_score": 90},
                {"symbol": "QQQ", "rank_score": 85},
            ],
            "shorts": [{"symbol": "TSLA", "rank_score": 92}],
        }

    async def fake_fusion(client, base_url, symbol, max_contract_cost):
        return {"symbol": symbol, "technical": {"signal": "LONG"}, "fusion_score": {"direction": "LONG", "score": 50, "coverage_pct": 70}}

    monkeypatch.setattr(worker, "fetch_radar", fake_radar)
    monkeypatch.setattr(worker, "fetch_fusion", fake_fusion)
    monkeypatch.setattr(worker, "classify_alert", lambda payload, **kwargs: {
        "alert": False,
        "state": "WATCH",
        "symbol": payload["symbol"],
        "direction": "LONG",
        "score": 50,
        "coverage_pct": 70,
    })

    results = asyncio.run(worker.scan_once(object(), worker.AlertState(tmp_path / "alert-state.json")))
    radar = results[0]
    assert radar["manual_focus"] == ["SMCI", "ARM", "MU", "AVGO"]
    assert radar["shortlist"][:4] == ["SMCI", "ARM", "MU", "AVGO"]
    assert len(radar["shortlist"]) == 6
    manual_rows = [row for row in results[1:] if row.get("manual_focus")]
    assert {row["symbol"] for row in manual_rows} == {"SMCI", "ARM", "MU", "AVGO"}
