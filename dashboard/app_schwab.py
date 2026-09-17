from __future__ import annotations

# Keep the established dashboard application intact and add the Schwab/thinkorswim
# integration as a separate router. This makes the broker integration removable
# and testable without coupling it to the existing Alpaca market-data code.
from app import app
from schwab_api import router as schwab_router

app.include_router(schwab_router)
