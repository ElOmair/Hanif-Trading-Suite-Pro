from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from manual_focus import list_focus_items, remove_focus_item, upsert_focus_item

router = APIRouter(prefix="/api/mnt/focus", tags=["mnt-focus"])


class FocusItemRequest(BaseModel):
    symbol: str = Field(min_length=1, max_length=10)
    kind: str = "WATCHING"
    direction: str = "AUTO"
    entry_price: float | None = Field(default=None, gt=0)
    contract: str | None = Field(default=None, max_length=80)
    note: str | None = Field(default=None, max_length=240)


@router.get("")
def get_focus() -> dict[str, Any]:
    items = list_focus_items()
    return {
        "items": items,
        "count": len(items),
        "research_only": True,
        "note": "Manual focus symbols receive priority review but do not authorize order placement.",
    }


@router.post("")
def save_focus(request: FocusItemRequest) -> dict[str, Any]:
    try:
        item = upsert_focus_item(**request.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"saved": True, "item": item, "research_only": True}


@router.delete("/{symbol}")
def delete_focus(symbol: str) -> dict[str, Any]:
    try:
        removed = remove_focus_item(symbol)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not removed:
        raise HTTPException(status_code=404, detail="Symbol is not in manual focus")
    return {"removed": True, "symbol": symbol.strip().upper(), "research_only": True}
