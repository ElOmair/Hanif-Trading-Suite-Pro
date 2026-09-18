from __future__ import annotations

import json
import os
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SYMBOL_RE = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")
VALID_KINDS = {"WATCHING", "OPEN_STOCK", "OPEN_OPTION"}
VALID_DIRECTIONS = {"AUTO", "LONG", "SHORT"}
_LOCK = threading.Lock()
ROOT = Path(__file__).resolve().parent


def _path() -> Path:
    return Path(os.getenv("MNT_MANUAL_FOCUS_FILE", str(ROOT / "data" / "mnt_manual_focus.json")))


def _max_items() -> int:
    try:
        value = int(os.getenv("MNT_MANUAL_FOCUS_MAX", "8"))
    except (TypeError, ValueError):
        value = 8
    return max(1, min(20, value))


def _load_unlocked() -> list[dict[str, Any]]:
    path = _path()
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, dict)]


def _save_unlocked(items: list[dict[str, Any]]) -> None:
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(items, indent=2, sort_keys=True), encoding="utf-8")
    os.chmod(temp, 0o600)
    temp.replace(path)
    os.chmod(path, 0o600)


def _normalize(
    *,
    symbol: str,
    kind: str = "WATCHING",
    direction: str = "AUTO",
    entry_price: float | None = None,
    contract: str | None = None,
    note: str | None = None,
    existing: dict[str, Any] | None = None,
) -> dict[str, Any]:
    symbol = str(symbol or "").strip().upper()
    if not SYMBOL_RE.fullmatch(symbol):
        raise ValueError("Invalid symbol")

    kind = str(kind or "WATCHING").strip().upper()
    if kind not in VALID_KINDS:
        raise ValueError("Invalid focus kind")

    direction = str(direction or "AUTO").strip().upper()
    if direction not in VALID_DIRECTIONS:
        raise ValueError("Invalid direction")

    parsed_entry: float | None = None
    if entry_price not in (None, ""):
        parsed_entry = float(entry_price)
        if parsed_entry <= 0:
            raise ValueError("Entry price must be positive")

    contract_text = str(contract or "").strip().upper()[:80] or None
    note_text = str(note or "").strip()[:240] or None
    now = datetime.now(timezone.utc).isoformat()
    previous = existing or {}
    return {
        "symbol": symbol,
        "kind": kind,
        "direction": direction,
        "entry_price": parsed_entry,
        "contract": contract_text if kind == "OPEN_OPTION" else None,
        "note": note_text,
        "added_at": previous.get("added_at") or now,
        "updated_at": now,
    }


def _sort_key(item: dict[str, Any]) -> tuple[int, str]:
    kind = str(item.get("kind") or "WATCHING").upper()
    priority = 0 if kind in {"OPEN_STOCK", "OPEN_OPTION"} else 1
    return priority, str(item.get("added_at") or "")


def list_focus_items() -> list[dict[str, Any]]:
    with _LOCK:
        items = _load_unlocked()
    return sorted(items, key=_sort_key)


def focus_symbols(limit: int | None = None) -> list[str]:
    items = list_focus_items()
    if limit is not None:
        items = items[: max(0, int(limit))]
    return [str(item.get("symbol") or "").upper() for item in items if item.get("symbol")]


def upsert_focus_item(
    *,
    symbol: str,
    kind: str = "WATCHING",
    direction: str = "AUTO",
    entry_price: float | None = None,
    contract: str | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    symbol_key = str(symbol or "").strip().upper()
    with _LOCK:
        items = _load_unlocked()
        existing = next((item for item in items if str(item.get("symbol") or "").upper() == symbol_key), None)
        if existing is None and len(items) >= _max_items():
            raise ValueError(f"Manual focus list is full ({_max_items()} max)")
        normalized = _normalize(
            symbol=symbol_key,
            kind=kind,
            direction=direction,
            entry_price=entry_price,
            contract=contract,
            note=note,
            existing=existing,
        )
        items = [item for item in items if str(item.get("symbol") or "").upper() != symbol_key]
        items.append(normalized)
        items = sorted(items, key=_sort_key)
        _save_unlocked(items)
    return normalized


def remove_focus_item(symbol: str) -> bool:
    symbol_key = str(symbol or "").strip().upper()
    if not SYMBOL_RE.fullmatch(symbol_key):
        raise ValueError("Invalid symbol")
    with _LOCK:
        items = _load_unlocked()
        kept = [item for item in items if str(item.get("symbol") or "").upper() != symbol_key]
        changed = len(kept) != len(items)
        if changed:
            _save_unlocked(kept)
    return changed
