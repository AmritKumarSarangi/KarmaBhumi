"""
api/routes/market.py – Market data endpoints.

GET /api/orderbook/{symbol}      – order book snapshot (Redis cache → gRPC)
GET /api/trades/{symbol}         – recent trades from DB
GET /api/market/stats/{symbol}   – VWAP, spread, volume from gRPC
GET /api/market/symbols          – all tradeable symbols with last price
"""
from __future__ import annotations

import json
import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from redis import asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import desc, select, func
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from db.database import get_db
from db.models import Trade
from grpc_client import grpc_client

logger = logging.getLogger(__name__)

router = APIRouter(tags=["market"])

# Known tradeable symbols (could be loaded from DB or config)
_SYMBOLS = ["AAPL", "GOOGL", "MSFT", "TSLA", "AMZN", "NVDA", "META", "NFLX"]


# ── Pydantic schemas ──────────────────────────────────────────────────────────


class PriceLevelOut(BaseModel):
    price: float
    quantity: int
    orders: int = 1


class OrderBookOut(BaseModel):
    symbol: str
    bids: list[PriceLevelOut]
    asks: list[PriceLevelOut]
    best_bid: float
    best_ask: float
    spread: float
    mid_price: float
    sequence_number: int
    timestamp_ns: int
    cached: bool = False


class TradeOut(BaseModel):
    id: str
    symbol: str
    price: float
    quantity: int
    buy_order_id: str | None
    sell_order_id: str | None
    buyer_id: str | None
    seller_id: str | None
    timestamp: datetime

    class Config:
        from_attributes = True


class MarketStatsOut(BaseModel):
    symbol: str
    last_price: float
    open_price: float
    high_price: float
    low_price: float
    close_price: float
    volume: int
    vwap: float
    spread: float
    order_imbalance: float
    bid_depth: int
    ask_depth: int
    trade_count: int
    is_halted: bool
    circuit_breaker_limit: float


class SymbolInfoOut(BaseModel):
    symbol: str
    last_price: float
    is_halted: bool
    volume: int


# ── Helpers ───────────────────────────────────────────────────────────────────


async def _get_redis():
    try:
        return await aioredis.from_url(
            settings.REDIS_URL, encoding="utf-8", decode_responses=True
        )
    except Exception:
        return None


def _parse_price_level(level: dict) -> PriceLevelOut:
    """Parse a price level from either raw C++ format (qty) or formatted format (quantity)."""
    price = float(level.get("price", 0.0))
    # Handle both raw C++ format ("qty") and normalized format ("quantity")
    quantity = int(level.get("quantity", level.get("qty", 0)))
    orders = int(level.get("orders", level.get("order_count", 1)))
    return PriceLevelOut(price=price, quantity=quantity, orders=orders)


def _compute_book_stats(bids: list, asks: list, raw_data: dict) -> dict:
    """Compute best_bid, best_ask, spread, mid_price from level lists."""
    best_bid = float(raw_data.get("best_bid", 0.0))
    best_ask = float(raw_data.get("best_ask", 0.0))

    # If not in raw_data, compute from first bid/ask
    if best_bid == 0.0 and bids:
        best_bid = float(bids[0].get("price", 0.0))
    if best_ask == 0.0 and asks:
        best_ask = float(asks[0].get("price", 0.0))

    spread = best_ask - best_bid if best_bid > 0 and best_ask > 0 else 0.0
    mid_price = (best_bid + best_ask) / 2.0 if best_bid > 0 and best_ask > 0 else 0.0

    return {
        "best_bid": best_bid,
        "best_ask": best_ask,
        "spread": spread,
        "mid_price": mid_price,
        "sequence_number": int(raw_data.get("seq_num", raw_data.get("sequence_number", 0))),
        "timestamp_ns": int(raw_data.get("timestamp_ns", 0)),
    }


# ── Routes ────────────────────────────────────────────────────────────────────


@router.get("/api/orderbook/{symbol}", response_model=OrderBookOut)
async def get_order_book(
    symbol: str,
    depth: int = Query(default=10, ge=1, le=100),
) -> OrderBookOut:
    sym = symbol.upper()

    # Try Redis cache first
    redis = await _get_redis()
    if redis:
        try:
            cached_raw = await redis.get(f"orderbook:{sym}")
            await redis.close()
            if cached_raw:
                data = json.loads(cached_raw)
                raw_bids = data.get("bids", [])
                raw_asks = data.get("asks", [])
                stats = _compute_book_stats(raw_bids, raw_asks, data)
                return OrderBookOut(
                    symbol=sym,
                    bids=[_parse_price_level(b) for b in raw_bids[:depth]],
                    asks=[_parse_price_level(a) for a in raw_asks[:depth]],
                    cached=True,
                    **stats,
                )
        except Exception as exc:
            logger.warning("Redis order book lookup failed: %s", exc)

    # Fall through to gRPC
    data = await grpc_client.get_order_book(sym, depth)
    return OrderBookOut(
        symbol=sym,
        bids=[_parse_price_level(b) for b in data.get("bids", [])],
        asks=[_parse_price_level(a) for a in data.get("asks", [])],
        best_bid=data.get("best_bid", 0.0),
        best_ask=data.get("best_ask", 0.0),
        spread=data.get("spread", 0.0),
        mid_price=data.get("mid_price", 0.0),
        sequence_number=data.get("sequence_number", 0),
        timestamp_ns=data.get("timestamp_ns", 0),
        cached=False,
    )


@router.get("/api/trades/{symbol}", response_model=list[TradeOut])
async def get_recent_trades(
    symbol: str,
    limit: int = Query(default=50, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
) -> list[TradeOut]:
    sym = symbol.upper()
    result = await db.execute(
        select(Trade)
        .where(Trade.symbol == sym)
        .order_by(desc(Trade.timestamp))
        .limit(limit)
    )
    trades = result.scalars().all()
    return [TradeOut.model_validate(t) for t in trades]


class CandleOut(BaseModel):
    time: int   # Unix timestamp seconds (minute boundary)
    open: float
    high: float
    low: float
    close: float
    volume: int


@router.get("/api/market/candles/{symbol}", response_model=list[CandleOut])
async def get_candles(
    symbol: str,
    interval: str = Query(default="1m"),
    limit: int = Query(default=200, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
) -> list[CandleOut]:
    """Build OHLCV candles from trades in DB."""
    sym = symbol.upper()
    interval_seconds = {
        "1m": 60, "5m": 300, "15m": 900, "1h": 3600, "1d": 86400
    }.get(interval, 60)

    # Fetch enough trades to build `limit` candles
    trades_limit = limit * 50  # rough upper bound
    result = await db.execute(
        select(Trade)
        .where(Trade.symbol == sym)
        .order_by(desc(Trade.timestamp))
        .limit(trades_limit)
    )
    trades = result.scalars().all()

    if not trades:
        return []

    # Group trades into candle buckets
    buckets: dict[int, dict] = defaultdict(lambda: {"open": None, "high": -1e18, "low": 1e18, "close": None, "volume": 0})
    for t in reversed(trades):  # oldest first
        ts = int(t.timestamp.replace(tzinfo=timezone.utc).timestamp())
        bucket_ts = (ts // interval_seconds) * interval_seconds
        b = buckets[bucket_ts]
        if b["open"] is None:
            b["open"] = t.price
        b["high"] = max(b["high"], t.price)
        b["low"] = min(b["low"], t.price)
        b["close"] = t.price
        b["volume"] += t.quantity

    candles = [
        CandleOut(time=ts, open=b["open"], high=b["high"], low=b["low"], close=b["close"], volume=b["volume"])
        for ts, b in sorted(buckets.items())
        if b["open"] is not None
    ]

    return candles[-limit:]  # return most recent `limit` candles


@router.get("/api/market/stats/{symbol}", response_model=MarketStatsOut)
async def get_market_stats(symbol: str, db: AsyncSession = Depends(get_db)) -> MarketStatsOut:
    sym = symbol.upper()

    # ── Real-time price from Redis orderbook ──────────────────────
    redis = await _get_redis()
    last_price = 0.0
    best_bid = 0.0
    best_ask = 0.0
    spread = 0.0
    if redis:
        try:
            cached_raw = await redis.get(f"orderbook:{sym}")
            await redis.close()
            if cached_raw:
                book = json.loads(cached_raw)
                raw_bids = book.get("bids", [])
                raw_asks = book.get("asks", [])
                if raw_bids:
                    best_bid = float(raw_bids[0].get("price", 0.0))
                if raw_asks:
                    best_ask = float(raw_asks[0].get("price", 0.0))
                if best_bid > 0 and best_ask > 0:
                    last_price = (best_bid + best_ask) / 2.0
                    spread = best_ask - best_bid
        except Exception as exc:
            logger.warning("Redis stats lookup failed: %s", exc)

    # ── Compute VWAP, volume, trade_count, high, low from DB ─────
    vwap = last_price
    volume = 0
    trade_count = 0
    high_price = last_price
    low_price = last_price
    open_price = last_price
    try:
        since = datetime.now(timezone.utc) - timedelta(hours=24)
        result = await db.execute(
            select(Trade)
            .where(Trade.symbol == sym)
            .where(Trade.timestamp >= since.replace(tzinfo=None))
            .order_by(Trade.timestamp)
        )
        db_trades = result.scalars().all()
        if db_trades:
            pv_sum = sum(t.price * t.quantity for t in db_trades)
            vol_sum = sum(t.quantity for t in db_trades)
            volume = vol_sum
            trade_count = len(db_trades)
            vwap = pv_sum / vol_sum if vol_sum > 0 else last_price
            high_price = max(t.price for t in db_trades)
            low_price = min(t.price for t in db_trades)
            open_price = db_trades[0].price  # first trade of the day
    except Exception as exc:
        logger.warning("DB stats computation failed: %s", exc)

    # ── Get halted status from gRPC ───────────────────────────────
    is_halted = False
    order_imbalance = 0.0
    try:
        gdata = await grpc_client.get_market_stats(sym)
        is_halted = gdata.get("is_halted", False)
        order_imbalance = gdata.get("order_imbalance", 0.0)
        # Use gRPC price only if Redis didn't provide one
        if last_price == 0.0:
            last_price = gdata.get("last_price", 0.0)
            vwap = last_price
    except Exception:
        pass

    return MarketStatsOut(
        symbol=sym,
        last_price=last_price,
        open_price=open_price,
        high_price=high_price,
        low_price=low_price,
        close_price=last_price,
        volume=volume,
        vwap=vwap,
        spread=spread,
        order_imbalance=order_imbalance,
        bid_depth=int(len(best_bid > 0 and [1] or [])),
        ask_depth=int(len(best_ask > 0 and [1] or [])),
        trade_count=trade_count,
        is_halted=is_halted,
        circuit_breaker_limit=0.0,
    )


@router.get("/api/market/symbols", response_model=list[SymbolInfoOut])
async def list_symbols() -> list[SymbolInfoOut]:
    results = []

    # Try to get real-time data from Redis for all symbols in one connection
    redis = await _get_redis()
    redis_books: dict[str, dict] = {}
    if redis:
        try:
            for sym in _SYMBOLS:
                raw = await redis.get(f"orderbook:{sym}")
                if raw:
                    redis_books[sym] = json.loads(raw)
            await redis.close()
        except Exception as exc:
            logger.warning("Redis bulk fetch failed: %s", exc)

    for sym in _SYMBOLS:
        last_price = 0.0
        is_halted = False
        volume = 0

        # Get price from Redis orderbook
        if sym in redis_books:
            book = redis_books[sym]
            bids = book.get("bids", [])
            asks = book.get("asks", [])
            if bids and asks:
                best_bid = float(bids[0].get("price", 0.0))
                best_ask = float(asks[0].get("price", 0.0))
                last_price = (best_bid + best_ask) / 2.0
            elif bids:
                last_price = float(bids[0].get("price", 0.0))
            elif asks:
                last_price = float(asks[0].get("price", 0.0))

        # Try gRPC for halted status and volume (non-blocking)
        try:
            stats = await grpc_client.get_market_stats(sym)
            is_halted = stats.get("is_halted", False)
            volume = int(stats.get("volume", 0))
            # Use gRPC price only if Redis didn't provide one
            if last_price == 0.0:
                last_price = stats.get("last_price", 0.0)
        except Exception:
            pass

        results.append(SymbolInfoOut(symbol=sym, last_price=last_price, is_halted=is_halted, volume=volume))

    return results
