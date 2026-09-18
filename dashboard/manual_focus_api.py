from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from kronos_api import fusion as kronos_fusion
from manual_focus import list_focus_items, remove_focus_item, upsert_focus_item
from option_position_manager import (
    build_option_position_analysis,
    find_exact_contract,
    missing_option_fields,
    option_spec_from_focus,
    underlying_price_from_chain,
)
from schwab_provider import option_chain

router = APIRouter(prefix="/api/mnt/focus", tags=["mnt-focus"])


class FocusItemRequest(BaseModel):
    symbol: str = Field(min_length=1, max_length=10)
    kind: str = "WATCHING"
    direction: str = "AUTO"
    entry_price: float | None = Field(default=None, gt=0)
    contract: str | None = Field(default=None, max_length=80)
    option_type: str | None = Field(default=None, max_length=8)
    strike: float | None = Field(default=None, gt=0)
    expiration: str | None = Field(default=None, max_length=10)
    quantity: int | None = Field(default=None, ge=1, le=100)
    note: str | None = Field(default=None, max_length=240)


def _focus_item(symbol: str) -> dict[str, Any] | None:
    key = str(symbol or "").strip().upper()
    return next((item for item in list_focus_items() if str(item.get("symbol") or "").upper() == key), None)


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


@router.get("/{symbol}/option-analysis")
async def option_position_analysis(
    symbol: str,
    deep: bool = Query(False, description="Run the full Kronos/Fusion thesis check in addition to the live option quote."),
) -> dict[str, Any]:
    item = _focus_item(symbol)
    if item is None:
        raise HTTPException(status_code=404, detail="Symbol is not in My Focus")
    if str(item.get("kind") or "").upper() != "OPEN_OPTION":
        raise HTTPException(status_code=400, detail="This My Focus item is not an open option position")

    missing = missing_option_fields(item)
    if missing:
        raise HTTPException(
            status_code=400,
            detail={
                "message": "Add the exact option details before MnT can manage this position.",
                "missing_fields": missing,
            },
        )

    spec = option_spec_from_focus(item)
    try:
        chain = await option_chain(
            spec["symbol"],
            contractType=spec["option_type"],
            strike=spec["strike"],
            fromDate=spec["expiration"],
            toDate=spec["expiration"],
            includeUnderlyingQuote=True,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Schwab option data unavailable: {type(exc).__name__}: {exc}") from exc

    chain_payload = chain if isinstance(chain, dict) else {}
    contract = find_exact_contract(chain_payload, spec)
    if contract is None:
        # Some Schwab chain responses ignore exact-strike filtering around unusual
        # roots. Retry a wider same-expiration chain before declaring it missing.
        try:
            chain = await option_chain(
                spec["symbol"],
                contractType=spec["option_type"],
                strikeCount=80,
                fromDate=spec["expiration"],
                toDate=spec["expiration"],
                includeUnderlyingQuote=True,
            )
            chain_payload = chain if isinstance(chain, dict) else {}
            contract = find_exact_contract(chain_payload, spec)
        except Exception:
            contract = None
    if contract is None:
        raise HTTPException(
            status_code=404,
            detail="The exact option contract was not found in the live Schwab chain. Verify expiration, strike and call/put.",
        )

    fusion_payload: dict[str, Any] | None = None
    deep_error: str | None = None
    if deep:
        try:
            # The current position is being analyzed, not selected. A generous cap
            # avoids rejecting the existing contract simply because today's ask is
            # above the normal new-trade budget.
            analysis_cap = max(1000.0, float(spec.get("entry_price") or 0.0) * 100.0 * 3.0)
            fusion_payload = await kronos_fusion(spec["symbol"], max_contract_cost=analysis_cap)
        except Exception as exc:
            deep_error = f"{type(exc).__name__}: {exc}"

    analysis = build_option_position_analysis(
        item,
        contract,
        underlying_price=underlying_price_from_chain(chain_payload),
        fusion=fusion_payload,
    )
    analysis["deep_analysis_requested"] = deep
    analysis["deep_analysis_available"] = fusion_payload is not None
    if deep_error:
        analysis["deep_analysis_error"] = deep_error
        analysis["management"]["note"] += " Live option management is still available, but the deeper Kronos thesis check failed on this request."
    return analysis


@router.delete("/{symbol}")
def delete_focus(symbol: str) -> dict[str, Any]:
    try:
        removed = remove_focus_item(symbol)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not removed:
        raise HTTPException(status_code=404, detail="Symbol is not in manual focus")
    return {"removed": True, "symbol": symbol.strip().upper(), "research_only": True}
