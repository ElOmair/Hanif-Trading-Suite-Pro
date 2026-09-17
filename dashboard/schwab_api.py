from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse

from kronos_api import _directional_features
from schwab_contracts import rank_option_candidates
from schwab_fundamentals import score_equity_quote
from schwab_portfolio import build_symbol_context, underlying_symbol
from schwab_position_manager import build_portfolio_reviews
from schwab_provider import begin_oauth, configured, exchange_code, option_chain, positions, quotes, token_status

router = APIRouter(prefix="/api/schwab", tags=["schwab"])


def _http_error(exc: Exception) -> HTTPException:
    text = str(exc)
    status = 401 if "authorize again" in text.lower() or "refresh token" in text.lower() else 502
    if "not configured" in text.lower():
        status = 503
    return HTTPException(status_code=status, detail=f"Schwab API: {type(exc).__name__}: {text}")


def _quote_for_symbol(payload: Any, symbol: str) -> dict[str, Any]:
    target = symbol.strip().upper()
    if isinstance(payload, dict):
        direct = payload.get(target) or payload.get(symbol) or payload.get(symbol.lower())
        if isinstance(direct, dict):
            return direct
        if str(payload.get("symbol") or "").upper() == target:
            return payload
    if isinstance(payload, list):
        for row in payload:
            if isinstance(row, dict) and str(row.get("symbol") or "").upper() == target:
                return row
    return {}


@router.get("/status")
def status() -> dict[str, Any]:
    payload = token_status()
    payload["order_submission_enabled"] = False
    payload["phase"] = "READ_ONLY_PHASE_1"
    payload["research_only"] = True
    return payload


@router.get("/authorize")
def authorize() -> RedirectResponse:
    try:
        return RedirectResponse(begin_oauth(), status_code=302)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get("/auth-url")
def auth_url() -> dict[str, Any]:
    try:
        return {"authorization_url": begin_oauth(), "configured": configured()}
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get("/callback", response_class=HTMLResponse)
async def callback(code: str = Query(...), state: str | None = Query(None)) -> HTMLResponse:
    try:
        await exchange_code(code, state)
    except Exception as exc:
        raise _http_error(exc) from exc
    return HTMLResponse(
        """
        <!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1">
        <title>MnT Schwab Connected</title></head><body style="font-family:system-ui;padding:2rem;max-width:720px;margin:auto">
        <h1>Schwab / thinkorswim connected</h1>
        <p>MnT stored the OAuth tokens on the server. No token or account number was sent to the browser.</p>
        <p>You can close this tab and return to the MnT dashboard.</p>
        </body></html>
        """
    )


@router.get("/positions")
async def account_positions() -> dict[str, Any]:
    try:
        return await positions()
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get("/portfolio/review")
async def portfolio_review() -> dict[str, Any]:
    """Review connected positions using current local MnT technical direction.

    This is research-only position management guidance and never submits orders.
    """
    try:
        payload = await positions()
        symbols: set[str] = set()
        for account in payload.get("accounts") or []:
            for row in account.get("positions") or []:
                symbol = underlying_symbol(row.get("symbol"), row.get("asset_type"))
                if symbol:
                    symbols.add(symbol)

        technical_by_symbol: dict[str, dict[str, Any]] = {}
        unavailable: list[str] = []
        for symbol in sorted(symbols):
            try:
                technical_by_symbol[symbol] = _directional_features(symbol)
            except Exception:
                unavailable.append(symbol)

        report = build_portfolio_reviews(payload, technical_by_symbol=technical_by_symbol)
        report["technical_symbols_available"] = sorted(technical_by_symbol)
        report["technical_symbols_unavailable"] = unavailable
        return report
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get("/portfolio/{symbol}/context")
async def portfolio_context(
    symbol: str,
    direction: str | None = Query(None, pattern="^(LONG|SHORT)$"),
) -> dict[str, Any]:
    try:
        payload = await positions()
        context = build_symbol_context(payload, symbol, intended_direction=direction)
        context["provider"] = "schwab"
        context["research_only"] = True
        return context
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get("/fundamentals/{symbol}")
async def fundamental_snapshot(symbol: str) -> dict[str, Any]:
    """Return a screening-grade equity fundamental snapshot from Schwab quote data."""
    target = symbol.strip().upper()
    try:
        raw = await quotes([target])
        quote = _quote_for_symbol(raw, target)
        snapshot = score_equity_quote(target, quote)
        snapshot["provider"] = "schwab"
        snapshot["research_only"] = True
        return snapshot
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get("/quotes")
async def market_quotes(symbols: str = Query(..., min_length=1, max_length=300)) -> Any:
    requested = [item.strip().upper() for item in symbols.split(",") if item.strip()]
    if len(requested) > 50:
        raise HTTPException(status_code=400, detail="Maximum 50 symbols per quote request")
    try:
        return await quotes(requested)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get("/options/{symbol}/candidates")
async def option_candidates(
    symbol: str,
    direction: str = Query(..., pattern="^(LONG|SHORT)$"),
    style: str = Query("auto", pattern="^(auto|intraday|0dte|day|swing|position)$"),
    max_contract_cost: float = Query(300.0, gt=0, le=100000),
    limit: int = Query(3, ge=1, le=10),
    strike_count: int = Query(40, ge=5, le=100),
    from_date: str | None = Query(None),
    to_date: str | None = Query(None),
) -> dict[str, Any]:
    try:
        raw = await option_chain(
            symbol,
            contractType="CALL" if direction == "LONG" else "PUT",
            strikeCount=strike_count,
            fromDate=from_date,
            toDate=to_date,
            includeUnderlyingQuote=True,
        )
        candidates = rank_option_candidates(
            raw if isinstance(raw, dict) else {},
            direction=direction,
            max_contract_cost=max_contract_cost,
            style=style,
            limit=limit,
        )
        return {
            "symbol": symbol.strip().upper(),
            "direction": direction,
            "style": style,
            "max_contract_cost": max_contract_cost,
            "provider": "schwab",
            "candidates": candidates,
            "candidate_count": len(candidates),
            "research_only": True,
        }
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get("/options/{symbol}")
async def options(
    symbol: str,
    contract_type: str | None = Query(None),
    strike_count: int | None = Query(20, ge=1, le=100),
    from_date: str | None = Query(None),
    to_date: str | None = Query(None),
    range_: str | None = Query(None, alias="range"),
) -> Any:
    try:
        return await option_chain(
            symbol,
            contractType=contract_type,
            strikeCount=strike_count,
            fromDate=from_date,
            toDate=to_date,
            range=range_,
            includeUnderlyingQuote=True,
        )
    except Exception as exc:
        raise _http_error(exc) from exc
