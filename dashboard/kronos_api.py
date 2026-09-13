from __future__ import annotations

import asyncio
import os
import re
import sys
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/api/kronos", tags=["kronos"])

KRONOS_ROOT = Path(os.getenv("KRONOS_ROOT", "/home/airomair/Kronos"))
MARKET_DATA_SCRIPT = KRONOS_ROOT / "trading" / "market_data.py"
ENSEMBLE_SCRIPT = KRONOS_ROOT / "trading" / "ensemble_forecast.py"
SYMBOL_RE = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")

# The Kronos model is GPU-backed. Keep dashboard-triggered analyses serialized so
# repeated clicks or multiple browser tabs cannot start overlapping forecasts.
_ANALYSIS_LOCK = asyncio.Lock()


def _number(pattern: str, text: str) -> float | None:
    match = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
    return float(match.group(1)) if match else None


def _integer_pair(pattern: str, text: str) -> tuple[int, int] | None:
    match = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
    return (int(match.group(1)), int(match.group(2))) if match else None


def _word(pattern: str, text: str) -> str | None:
    match = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
    return match.group(1).strip().upper() if match else None


def _parse_output(symbol: str, output: str) -> dict[str, Any]:
    bullish = _integer_pair(r"Bullish paths:\s*(\d+)\s*/\s*(\d+)", output)
    bearish = _integer_pair(r"Bearish paths:\s*(\d+)\s*/\s*(\d+)", output)
    neutral = _integer_pair(r"Neutral paths:\s*(\d+)\s*/\s*(\d+)", output)

    result: dict[str, Any] = {
        "symbol": symbol,
        "average_score": _number(r"Average score:\s*([+-]?\d+(?:\.\d+)?)", output),
        "median_1h_move_pct": _number(r"Median 1H move:\s*([+-]?\d+(?:\.\d+)?)%", output),
        "median_2h_move_pct": _number(r"Median 2H move:\s*([+-]?\d+(?:\.\d+)?)%", output),
        "score_spread": _number(r"Score spread:\s*([+-]?\d+(?:\.\d+)?)", output),
        "score_std_dev": _number(r"Score std dev:\s*([+-]?\d+(?:\.\d+)?)", output),
        "bias_agreement_pct": _number(r"Bias agreement:\s*([+-]?\d+(?:\.\d+)?)%", output),
        "stability": _word(r"Stability:\s*([A-Za-z]+)", output),
        "final_bias": _word(r"FINAL BIAS:\s*([A-Za-z]+)", output),
        "action": _word(r"ACTION:\s*([A-Za-z]+)", output),
        "runtime_seconds": _number(r"Runtime:\s*([+-]?\d+(?:\.\d+)?)\s*sec", output),
        "peak_gpu_vram_mb": _number(r"Peak GPU VRAM:\s*([+-]?\d+(?:\.\d+)?)\s*MB", output),
        "source": "Kronos ensemble_forecast.py",
        "market_data_refreshed": True,
        "research_only": True,
    }
    if bullish:
        result["bullish_paths"], result["path_count"] = bullish
    if bearish:
        result["bearish_paths"] = bearish[0]
        result.setdefault("path_count", bearish[1])
    if neutral:
        result["neutral_paths"] = neutral[0]
        result.setdefault("path_count", neutral[1])
    return result


async def _run_script(script: Path, symbol: str, timeout: float, label: str) -> str:
    env = os.environ.copy()
    env.setdefault("PYTHONUNBUFFERED", "1")
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        str(script),
        symbol,
        cwd=str(KRONOS_ROOT),
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    try:
        stdout, _ = await asyncio.wait_for(process.communicate(), timeout=timeout)
    except TimeoutError:
        process.kill()
        await process.communicate()
        raise HTTPException(status_code=504, detail=f"{label} timed out")

    output = stdout.decode("utf-8", errors="replace")
    if process.returncode != 0:
        tail = "\n".join(output.strip().splitlines()[-14:])
        raise HTTPException(status_code=502, detail=f"{label} failed:\n{tail}")
    return output


@router.post("/analyze/{symbol}")
async def analyze(symbol: str) -> dict[str, Any]:
    symbol = symbol.strip().upper()
    if not SYMBOL_RE.fullmatch(symbol):
        raise HTTPException(status_code=400, detail="Invalid symbol")
    if not MARKET_DATA_SCRIPT.exists():
        raise HTTPException(status_code=503, detail=f"Kronos market-data script not found at {MARKET_DATA_SCRIPT}")
    if not ENSEMBLE_SCRIPT.exists():
        raise HTTPException(status_code=503, detail=f"Kronos ensemble script not found at {ENSEMBLE_SCRIPT}")

    async with _ANALYSIS_LOCK:
        # Always refresh the symbol's 5-minute Alpaca data first. This removes the
        # old requirement to manually run `python trading/market_data.py SYMBOL`
        # before using the dashboard's Run Kronos button.
        await _run_script(MARKET_DATA_SCRIPT, symbol, timeout=30, label="Market-data refresh")
        output = await _run_script(ENSEMBLE_SCRIPT, symbol, timeout=45, label="Kronos forecast")

    parsed = _parse_output(symbol, output)
    if parsed.get("final_bias") is None:
        tail = "\n".join(output.strip().splitlines()[-20:])
        raise HTTPException(status_code=502, detail=f"Kronos output could not be parsed:\n{tail}")
    return parsed
