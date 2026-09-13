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
ENSEMBLE_SCRIPT = KRONOS_ROOT / "trading" / "ensemble_forecast.py"
SYMBOL_RE = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")


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


@router.post("/analyze/{symbol}")
async def analyze(symbol: str) -> dict[str, Any]:
    symbol = symbol.strip().upper()
    if not SYMBOL_RE.fullmatch(symbol):
        raise HTTPException(status_code=400, detail="Invalid symbol")
    if not ENSEMBLE_SCRIPT.exists():
        raise HTTPException(status_code=503, detail=f"Kronos ensemble script not found at {ENSEMBLE_SCRIPT}")

    env = os.environ.copy()
    env.setdefault("PYTHONUNBUFFERED", "1")
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        str(ENSEMBLE_SCRIPT),
        symbol,
        cwd=str(KRONOS_ROOT),
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    try:
        stdout, _ = await asyncio.wait_for(process.communicate(), timeout=45)
    except TimeoutError:
        process.kill()
        await process.communicate()
        raise HTTPException(status_code=504, detail="Kronos forecast timed out")

    output = stdout.decode("utf-8", errors="replace")
    if process.returncode != 0:
        tail = "\n".join(output.strip().splitlines()[-12:])
        raise HTTPException(status_code=502, detail=f"Kronos forecast failed:\n{tail}")

    parsed = _parse_output(symbol, output)
    if parsed.get("final_bias") is None:
        tail = "\n".join(output.strip().splitlines()[-20:])
        raise HTTPException(status_code=502, detail=f"Kronos output could not be parsed:\n{tail}")
    return parsed
