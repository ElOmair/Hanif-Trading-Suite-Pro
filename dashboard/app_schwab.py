from __future__ import annotations

from pathlib import Path

from fastapi.responses import FileResponse

# Keep the established dashboard application intact and add the Schwab/thinkorswim
# integration as a separate router. This makes the broker integration removable
# and testable without coupling it to the existing Alpaca market-data code.
from app import app
from schwab_api import router as schwab_router

ROOT = Path(__file__).resolve().parent
app.include_router(schwab_router)


@app.get("/broker")
def broker_desk() -> FileResponse:
    return FileResponse(ROOT / "static" / "broker.html")
