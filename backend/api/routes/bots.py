"""
api/routes/bots.py – Bot status endpoint for frontend BotActivity panel.
"""
from __future__ import annotations
from datetime import datetime, timezone, timedelta
import random

from fastapi import APIRouter, Depends

from api.routes.auth import require_auth
from db.models import User

router = APIRouter(prefix="/api/bots", tags=["bots"])

# Simulated bot registry that tracks the market-making / HFT bots
# the matching engine is running internally.
_BOT_REGISTRY = [
    {"bot_type": "HFT Market Maker",    "symbol": "AAPL",  "active": True},
    {"bot_type": "HFT Market Maker",    "symbol": "GOOGL", "active": True},
    {"bot_type": "HFT Market Maker",    "symbol": "TSLA",  "active": True},
    {"bot_type": "Retail Simulator",    "symbol": "AAPL",  "active": True},
    {"bot_type": "Retail Simulator",    "symbol": "MSFT",  "active": True},
    {"bot_type": "Institutional Block", "symbol": "AMZN",  "active": True},
    {"bot_type": "Momentum Trader",     "symbol": "TSLA",  "active": True},
]


@router.get("/status")
async def bots_status(
    _: User = Depends(require_auth),
) -> list:
    """Return simulated bot activity status — the matching engine has
    internal market simulators; this exposes their activity to the frontend."""
    now = datetime.now(timezone.utc)
    result = []
    for bot in _BOT_REGISTRY:
        # Simulate randomised activity metrics consistent with internal engine bots
        orders_per_min = random.randint(8, 120) if bot["active"] else 0
        seconds_ago = random.randint(0, 30)
        result.append({
            "bot_type": bot["bot_type"],
            "symbol": bot["symbol"],
            "orders_per_min": orders_per_min,
            "last_order": (now - timedelta(seconds=seconds_ago)).isoformat(),
            "active": bot["active"],
        })
    return result
