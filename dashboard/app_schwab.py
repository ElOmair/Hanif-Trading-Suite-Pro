from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi.responses import FileResponse

# Keep the established dashboard application intact and add the Schwab/thinkorswim
# integration as separate routers. Market Focus is mounted explicitly on this app
# so the endpoint cannot be lost through router import-order differences.
from app import app
from manual_focus_api import router as manual_focus_router
from market_focus_api import market_focus as market_focus_handler
from mnt_decision_api import router as mnt_decision_router
from schwab_api import router as schwab_router

ROOT = Path(__file__).resolve().parent
app.include_router(schwab_router)
app.include_router(mnt_decision_router)
app.include_router(manual_focus_router)


@app.get("/api/market/focus", tags=["market-focus"])
async def market_focus_endpoint() -> dict[str, Any]:
    return await market_focus_handler()


@app.get("/broker")
def broker_desk() -> FileResponse:
    return FileResponse(ROOT / "static" / "broker.html")
