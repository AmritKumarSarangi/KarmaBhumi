"""
api/websocket.py – WebSocket connection manager + heartbeat + fan-out broadcast.

Clients connect to:  ws://host/ws/{symbol}?token=<JWT>

Message envelope:
  { "type": "trade" | "book" | "alert" | "stats" | "ping" | "error",
    "data": { ... } }
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import defaultdict
from typing import Any

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect, status

from config import settings
from monitoring.metrics import active_websocket_connections

logger = logging.getLogger(__name__)

router = APIRouter()

_HEARTBEAT_INTERVAL = 30  # seconds


# ── Connection Manager ────────────────────────────────────────────────────────


class ConnectionManager:
    """Manages WebSocket connections grouped by symbol and by user_id."""

    def __init__(self) -> None:
        # symbol -> set of websockets
        self._symbol_connections: dict[str, set[WebSocket]] = defaultdict(set)
        # user_id -> set of websockets (for targeted alerts)
        self._user_connections: dict[str, set[WebSocket]] = defaultdict(set)
        # websocket -> metadata
        self._meta: dict[WebSocket, dict[str, Any]] = {}

    # ── Lifecycle ─────────────────────────────────────────────

    async def connect(
        self, websocket: WebSocket, user_id: str, symbol: str
    ) -> None:
        await websocket.accept()
        self._symbol_connections[symbol].add(websocket)
        self._user_connections[user_id].add(websocket)
        self._meta[websocket] = {
            "user_id": user_id,
            "symbol": symbol,
            "connected_at": time.time(),
            "last_ping": time.time(),
        }
        active_websocket_connections.labels(symbol=symbol).inc()
        logger.info("WS connect user=%s symbol=%s", user_id, symbol)

    def disconnect(self, websocket: WebSocket) -> None:
        meta = self._meta.pop(websocket, None)
        if meta is None:
            return
        symbol = meta["symbol"]
        user_id = meta["user_id"]
        self._symbol_connections[symbol].discard(websocket)
        self._user_connections[user_id].discard(websocket)
        if not self._symbol_connections[symbol]:
            del self._symbol_connections[symbol]
        if not self._user_connections[user_id]:
            del self._user_connections[user_id]
        active_websocket_connections.labels(symbol=symbol).dec()
        logger.info("WS disconnect user=%s symbol=%s", user_id, symbol)

    # ── Broadcast helpers ─────────────────────────────────────

    async def _send(self, websocket: WebSocket, payload: dict) -> None:
        try:
            await websocket.send_text(json.dumps(payload, default=str))
        except Exception:
            self.disconnect(websocket)

    async def broadcast_trade(self, symbol: str, trade_data: dict) -> None:
        payload = {"type": "trade", "data": trade_data}
        connections = set(self._symbol_connections.get(symbol, set()))
        if connections:
            await asyncio.gather(*(self._send(ws, payload) for ws in connections))

    async def broadcast_book_update(self, symbol: str, book_data: dict) -> None:
        payload = {"type": "book", "data": book_data}
        connections = set(self._symbol_connections.get(symbol, set()))
        if connections:
            await asyncio.gather(*(self._send(ws, payload) for ws in connections))

    async def broadcast_alert(self, user_id: str, alert_data: dict) -> None:
        payload = {"type": "alert", "data": alert_data}
        connections = set(self._user_connections.get(user_id, set()))
        if connections:
            await asyncio.gather(*(self._send(ws, payload) for ws in connections))

    async def broadcast_stats(self, symbol: str, stats_data: dict) -> None:
        payload = {"type": "stats", "data": stats_data}
        connections = set(self._symbol_connections.get(symbol, set()))
        if connections:
            await asyncio.gather(*(self._send(ws, payload) for ws in connections))

    async def broadcast_to_all(self, payload: dict) -> None:
        all_sockets = set(self._meta.keys())
        if all_sockets:
            await asyncio.gather(*(self._send(ws, payload) for ws in all_sockets))

    # ── Heartbeat ─────────────────────────────────────────────

    async def heartbeat_loop(self) -> None:
        """Send ping frames to all connected clients every 30 s."""
        while True:
            await asyncio.sleep(_HEARTBEAT_INTERVAL)
            now = time.time()
            all_sockets = set(self._meta.keys())
            for ws in all_sockets:
                await self._send(ws, {"type": "ping", "ts": now})

    @property
    def connection_count(self) -> int:
        return len(self._meta)


# ── Singleton ─────────────────────────────────────────────────────────────────
manager = ConnectionManager()


# ── Endpoint helpers ──────────────────────────────────────────────────────────

def _verify_token(token: str) -> str | None:
    """Return user_id if token is valid, else None."""
    from jose import JWTError, jwt  # lazy import to avoid circular dep

    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
        return payload.get("sub")
    except JWTError:
        return None


# ── WebSocket route: market data ──────────────────────────────────────────────


@router.websocket("/ws/{symbol}")
async def websocket_market(
    websocket: WebSocket,
    symbol: str,
    token: str | None = Query(default=None),
) -> None:
    import uuid
    user_id = None
    if token:
        user_id = _verify_token(token)
    
    if not user_id:
        user_id = f"anonymous_{uuid.uuid4()}"

    await manager.connect(websocket, user_id, symbol.upper())
    try:
        # ── Send snapshot immediately from Redis ──────────────────
        try:
            from redis import asyncio as aioredis
            from config import settings as _settings
            import json as _json
            import datetime as _dt
            redis = await aioredis.from_url(_settings.REDIS_URL, encoding="utf-8", decode_responses=True)
            cached_raw = await redis.get(f"orderbook:{symbol.upper()}")
            await redis.close()
            if cached_raw:
                book_data = _json.loads(cached_raw)
                # Normalize to frontend format
                bids = []
                cum = 0
                for b in book_data.get("bids", []):
                    qty = b.get("qty", b.get("quantity", 0))
                    cum += qty
                    bids.append({"price": b.get("price", 0.0), "quantity": qty, "total": cum})
                asks = []
                cum = 0
                for a in book_data.get("asks", []):
                    qty = a.get("qty", a.get("quantity", 0))
                    cum += qty
                    asks.append({"price": a.get("price", 0.0), "quantity": qty, "total": cum})
                snap = {
                    "symbol": symbol.upper(),
                    "bids": bids,
                    "asks": asks,
                    "timestamp": _dt.datetime.utcnow().isoformat() + "Z",
                }
                await websocket.send_text(_json.dumps({"type": "book", "data": snap}))
        except Exception as exc:
            logger.warning("WS initial snapshot failed: %s", exc)

        while True:
            # Keep connection open; client may send pong/ping ACKs
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=_HEARTBEAT_INTERVAL + 5)
                try:
                    msg = json.loads(data)
                    if msg.get("type") == "pong":
                        meta = manager._meta.get(websocket)
                        if meta:
                            meta["last_ping"] = time.time()
                except json.JSONDecodeError:
                    pass
            except asyncio.TimeoutError:
                # Client hasn't sent anything; that's OK (we push)
                pass
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as exc:
        logger.error("WS error for user=%s symbol=%s: %s", user_id, symbol, exc)
        manager.disconnect(websocket)
