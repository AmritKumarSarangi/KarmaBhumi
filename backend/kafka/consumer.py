"""
kafka/consumer.py – aiokafka-based consumer service.

Topics consumed:
  - trades              → persist to DB + broadcast via WebSocket
  - order-book-updates  → cache in Redis + broadcast via WebSocket
  - risk-alerts         → broadcast targeted alert to user WebSocket
  - market-data         → broadcast stats to symbol subscribers

Run as a background asyncio Task during app lifespan.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any

from aiokafka import AIOKafkaConsumer
from aiokafka.errors import KafkaError

from config import settings
from monitoring.metrics import kafka_messages_consumed_total, kafka_consumer_errors_total

logger = logging.getLogger(__name__)

_TOPICS = ["trades", "order-book-updates", "risk-alerts", "market-data"]


class KafkaConsumerService:
    """Background service that consumes Kafka topics and fan-outs to WebSockets."""

    def __init__(self) -> None:
        self._consumer: AIOKafkaConsumer | None = None
        self._running = False
        self._task: asyncio.Task | None = None

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    async def start(self) -> None:
        from api.websocket import manager  # avoid circular at module level

        self._manager = manager
        self._running = True
        self._task = asyncio.create_task(self._run(), name="kafka-consumer")
        logger.info("Kafka consumer task started; topics=%s", _TOPICS)

    async def stop(self) -> None:
        self._running = False
        if self._consumer:
            await self._consumer.stop()
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Kafka consumer stopped")

    # ── Main loop ─────────────────────────────────────────────────────────────

    async def _run(self) -> None:
        """Outer loop: reconnect indefinitely on failures."""
        while self._running:
            try:
                await self._consume_loop()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("Kafka consumer crashed: %s – reconnecting in 5s", exc)
                await asyncio.sleep(5)

    async def _consume_loop(self) -> None:
        brokers = ",".join(settings.kafka_brokers_list)
        self._consumer = AIOKafkaConsumer(
            *_TOPICS,
            bootstrap_servers=brokers,
            group_id=settings.KAFKA_GROUP_ID,
            auto_offset_reset="latest",
            enable_auto_commit=True,
            value_deserializer=lambda v: json.loads(v.decode("utf-8", errors="replace")),
            key_deserializer=lambda k: k.decode("utf-8", errors="replace") if k else None,
        )
        await self._consumer.start()
        logger.info("Kafka consumer connected to %s", brokers)
        try:
            async for msg in self._consumer:
                if not self._running:
                    break
                await self._dispatch(msg)
        finally:
            await self._consumer.stop()

    async def _dispatch(self, msg: Any) -> None:
        topic = msg.topic
        try:
            data: dict = msg.value if isinstance(msg.value, dict) else {}
            kafka_messages_consumed_total.labels(topic=topic).inc()

            if topic == "trades":
                await self._handle_trade(data)
            elif topic == "order-book-updates":
                await self._handle_order_book(data)
            elif topic == "risk-alerts":
                await self._handle_risk_alert(data)
            elif topic == "market-data":
                await self._handle_market_data(data)
        except Exception as exc:
            kafka_consumer_errors_total.labels(topic=topic).inc()
            logger.error("Error dispatching Kafka msg topic=%s: %s", topic, exc)

    # ── Handlers ──────────────────────────────────────────────────────────────

    async def _handle_trade(self, data: dict) -> None:
        symbol = data.get("symbol", "")
        # Persist to DB
        try:
            await self._persist_trade(data)
        except Exception as exc:
            logger.error("Failed to persist trade: %s", exc)
        
        # Format for frontend
        import uuid
        formatted = {
            "id": data.get("trade_id", str(uuid.uuid4())),
            "symbol": symbol,
            "price": float(data.get("price", 0.0)),
            "quantity": int(data.get("quantity", 0)),
            "side": "buy" if data.get("buyer_user_id") else "sell",
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        # Broadcast
        await self._manager.broadcast_trade(symbol, formatted)

    async def _handle_order_book(self, data: dict) -> None:
        symbol = data.get("symbol", "")
        
        # Format for frontend
        bids = []
        cum = 0
        for b in data.get("bids", []):
            cum += b.get("qty", 0)
            bids.append({"price": b.get("price", 0.0), "quantity": b.get("qty", 0), "total": cum})
            
        asks = []
        cum = 0
        for a in data.get("asks", []):
            cum += a.get("qty", 0)
            asks.append({"price": a.get("price", 0.0), "quantity": a.get("qty", 0), "total": cum})
            
        formatted = {
            "symbol": symbol,
            "bids": bids,
            "asks": asks,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

        # Cache in Redis
        try:
            await self._cache_order_book(symbol, formatted)
        except Exception as exc:
            logger.error("Failed to cache order book: %s", exc)
        # Broadcast
        await self._manager.broadcast_book_update(symbol, formatted)

    async def _handle_risk_alert(self, data: dict) -> None:
        user_id = data.get("user_id", "")
        if user_id:
            await self._manager.broadcast_alert(user_id, data)
        else:
            # System-wide alert
            await self._manager.broadcast_to_all({"type": "alert", "data": data})

    async def _handle_market_data(self, data: dict) -> None:
        symbol = data.get("symbol", "")
        await self._manager.broadcast_stats(symbol, data)

    # ── Persistence ───────────────────────────────────────────────────────────

    async def _persist_trade(self, data: dict) -> None:
        """Write trade to PostgreSQL via async SQLAlchemy."""
        from db.database import AsyncSessionLocal
        from db.models import Trade, Event
        import uuid

        def _safe_uuid(val) -> str | None:
            """Return val only if it looks like a valid UUID, else None."""
            if not val or not isinstance(val, str) or len(val) < 32:
                return None
            try:
                uuid.UUID(val)
                return val
            except (ValueError, AttributeError):
                return None

        def _safe_str(val) -> str | None:
            """Return val as string if truthy, else None."""
            if not val or str(val) == "0":
                return None
            return str(val)

        try:
            async with AsyncSessionLocal() as session:
                trade = Trade(
                    id=str(uuid.uuid4()),
                    engine_trade_id=_safe_str(data.get("trade_id")),
                    symbol=data.get("symbol", ""),
                    price=float(data.get("price", 0)),
                    quantity=int(data.get("quantity", 0)),
                    buy_order_id=_safe_str(data.get("buy_order_id")),
                    sell_order_id=_safe_str(data.get("sell_order_id")),
                    buyer_id=_safe_uuid(data.get("buyer_user_id")),
                    seller_id=_safe_uuid(data.get("seller_user_id")),
                    timestamp=datetime.now(timezone.utc),
                )
                session.add(trade)

                # Event sourcing record
                seq = int(data.get("sequence_num", 0) or 0)
                event = Event(
                    event_type="TRADE_EXECUTED",
                    payload=data,
                    sequence_num=seq,
                    symbol=data.get("symbol"),
                    timestamp=datetime.now(timezone.utc),
                )
                session.add(event)
                await session.commit()
        except Exception as exc:
            logger.error("_persist_trade DB error: %s", exc)


    async def _cache_order_book(self, symbol: str, data: dict) -> None:
        """Cache the latest order book snapshot in Redis."""
        from redis import asyncio as aioredis

        try:
            redis = await aioredis.from_url(
                settings.REDIS_URL,
                encoding="utf-8",
                decode_responses=True,
            )
            key = f"orderbook:{symbol}"
            await redis.set(key, json.dumps(data), ex=settings.ORDER_BOOK_CACHE_TTL_SECONDS)
            await redis.close()
        except Exception as exc:
            logger.warning("Redis cache_order_book failed: %s", exc)


# ── Singleton ─────────────────────────────────────────────────────────────────
kafka_consumer = KafkaConsumerService()
