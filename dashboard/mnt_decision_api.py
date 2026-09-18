from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from kronos_api import fusion as kronos_fusion
from mnt_engine import build_fusion_score
from schwab_api import accounts_enabled
from schwab_contracts import rank_option_candidates
from schwab_portfolio import build_symbol_context
from schwab_provider import option_chain, positions, token_status

router = APIRouter(prefix="/api/mnt", tags=["mnt-decision"])


def _decision_label(value: Any) -> str:
    if isinstance(value, str):
        return value.strip().upper()
    if isinstance(value, dict):
        for key in ("decision", "action", "state", "status"):
            if value.get(key):
                return str(value[key]).strip().upper()
    return "UNKNOWN"


def _portfolio_gate(context: dict[str, Any] | None) -> dict[str, Any]:
    if not context or context.get("available") is False:
        return {
            "state": "NOT_IN_USE",
            "allow_add": None,
            "reason": "Portfolio awareness is intentionally disabled while Schwab is used for market-data analysis only.",
        }

    relationship = str(context.get("relationship") or "UNKNOWN").upper()
    risk = str(context.get("risk_level") or "LOW").upper()
    concentration = float(context.get("concentration_pct") or 0.0)

    if relationship == "CONFLICT":
        return {
            "state": "BLOCK_ADD",
            "allow_add": False,
            "reason": "The proposed setup points against an existing position. Treat it as a hedge/reversal decision, not a new trade.",
        }
    if risk == "HIGH" or concentration >= 20.0:
        return {
            "state": "BLOCK_ADD",
            "allow_add": False,
            "reason": "Existing exposure is already highly concentrated. MnT should not recommend adding more risk automatically.",
        }
    if relationship in {"ALREADY_EXPOSED", "MIXED"} or risk in {"ELEVATED", "MODERATE"}:
        return {
            "state": "REVIEW_ADD",
            "allow_add": True,
            "reason": "There is existing exposure or meaningful concentration. Any additional position should be treated as an add-on and reviewed separately.",
        }
    if relationship == "NEW":
        return {
            "state": "OK_NEW",
            "allow_add": True,
            "reason": "No conflicting position was found in the connected Schwab accounts.",
        }
    return {
        "state": "REVIEW",
        "allow_add": True,
        "reason": "Portfolio context is mixed or incomplete; review existing exposure before adding risk.",
    }


async def _schwab_overlay(
    payload: dict[str, Any],
    *,
    max_contract_cost: float,
) -> dict[str, Any]:
    status = token_status()
    connected = bool(status.get("configured") and status.get("authorized") and status.get("refresh_token_valid"))
    account_reads = accounts_enabled()
    overlay: dict[str, Any] = {
        "available": connected,
        "market_data_available": connected,
        "accounts_available": connected and account_reads,
        "provider": "schwab",
        "analysis_mode": "MARKET_DATA_ONLY" if not account_reads else "MARKET_DATA_PLUS_ACCOUNTS",
        "phase": "READ_ONLY_ANALYSIS",
        "research_only": True,
        "portfolio_context": None,
        "portfolio_gate": _portfolio_gate(None),
        "option_candidates": [],
        "preferred_contract_provider": "kronos" if payload.get("options") else None,
        "preferred_options": payload.get("options") or [],
        "broker_adjusted_fusion_score": None,
    }
    if not connected:
        overlay["reason"] = "Schwab/thinkorswim is not connected yet. MnT is using its existing research layers without Schwab market data."
        return overlay

    symbol = str(payload.get("symbol") or "").strip().upper()
    technical = payload.get("technical") or {}
    direction = str(technical.get("signal") or (payload.get("fusion_score") or {}).get("direction") or "").upper()

    if account_reads:
        try:
            portfolio = await positions()
            context = build_symbol_context(portfolio, symbol, intended_direction=direction if direction in {"LONG", "SHORT"} else None)
            context["provider"] = "schwab"
            context["research_only"] = True
            context["available"] = True
            overlay["portfolio_context"] = context
            overlay["portfolio_gate"] = _portfolio_gate(context)
        except Exception as exc:
            overlay["portfolio_error"] = f"{type(exc).__name__}: {exc}"
    else:
        overlay["portfolio_context"] = {
            "available": False,
            "relationship": "UNKNOWN",
            "action_note": "Schwab account and position reads are intentionally disabled during analysis-only testing.",
        }
        overlay["portfolio_gate"] = _portfolio_gate(overlay["portfolio_context"])

    label = _decision_label(payload.get("decision"))
    should_scan = direction in {"LONG", "SHORT"} and not any(term in label for term in ("REJECT", "NO_DIRECTION"))
    if should_scan:
        try:
            raw = await option_chain(
                symbol,
                contractType="CALL" if direction == "LONG" else "PUT",
                strikeCount=40,
                includeUnderlyingQuote=True,
            )
            candidates = rank_option_candidates(
                raw if isinstance(raw, dict) else {},
                direction=direction,
                max_contract_cost=max_contract_cost,
                style="auto",
                limit=3,
            )
            overlay["option_candidates"] = candidates
            if candidates:
                overlay["preferred_contract_provider"] = "schwab"
                overlay["preferred_options"] = candidates
                overlay["broker_adjusted_fusion_score"] = build_fusion_score(
                    technical=technical,
                    kronos=payload.get("kronos"),
                    gamma=payload.get("gamma"),
                    flow=payload.get("flow"),
                    market=payload.get("market_regime"),
                    options=candidates,
                )
        except Exception as exc:
            overlay["option_error"] = f"{type(exc).__name__}: {exc}"

    return overlay


@router.post("/decision/{symbol}")
async def broker_aware_decision(
    symbol: str,
    max_contract_cost: float = Query(300.0, gt=0, le=100000),
) -> dict[str, Any]:
    """Return the normal MnT Fusion result plus read-only Schwab analysis context.

    This endpoint never submits, replaces, or cancels a brokerage order.
    """
    try:
        payload = await kronos_fusion(symbol, max_contract_cost=max_contract_cost)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"MnT Fusion failed: {type(exc).__name__}: {exc}") from exc

    overlay = await _schwab_overlay(payload, max_contract_cost=max_contract_cost)
    result = dict(payload)
    result["broker"] = overlay
    result["preferred_options"] = overlay.get("preferred_options") or payload.get("options") or []
    result["preferred_contract_provider"] = overlay.get("preferred_contract_provider")
    result["effective_fusion_score"] = overlay.get("broker_adjusted_fusion_score") or payload.get("fusion_score")
    result["research_only"] = True
    result["order_submission_enabled"] = False
    return result
