"""
grpc_client.py – Async wrapper around the gRPC ExchangeService stub.

The C++ matching engine exposes a synchronous gRPC server at
MATCHING_ENGINE_HOST:50051.  Because grpcio stubs are synchronous, every call
is dispatched to a thread-pool executor so it never blocks the event loop.

Retry logic with exponential back-off is applied on transient errors.
If the engine is completely unreachable, mock data is returned so the
frontend remains functional.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from functools import wraps
from typing import Any

import grpc

from config import settings
from monitoring.metrics import (
    grpc_call_duration_seconds,
    grpc_calls_total,
    engine_p50_latency_ns,
    engine_p95_latency_ns,
    engine_p99_latency_ns,
    engine_p999_latency_ns,
    engine_orders_per_second,
    engine_trades_per_second,
)

logger = logging.getLogger(__name__)

# Generated protobuf stubs (created by Dockerfile protoc step)
try:
    import exchange_pb2 as pb2  # type: ignore
    import exchange_pb2_grpc as pb2_grpc  # type: ignore

    _STUBS_AVAILABLE = True
except ImportError:  # pragma: no cover
    logger.warning("gRPC stubs not found – running in mock mode")
    _STUBS_AVAILABLE = False


# ── Helpers ───────────────────────────────────────────────────────────────────

_RETRYABLE = {
    grpc.StatusCode.UNAVAILABLE,
    grpc.StatusCode.DEADLINE_EXCEEDED,
    grpc.StatusCode.RESOURCE_EXHAUSTED,
}


def _proto_order_book_to_dict(snapshot: Any) -> dict:
    return {
        "symbol": snapshot.symbol,
        "bids": [
            {"price": l.price, "quantity": l.total_quantity, "orders": l.order_count}
            for l in snapshot.bids
        ],
        "asks": [
            {"price": l.price, "quantity": l.total_quantity, "orders": l.order_count}
            for l in snapshot.asks
        ],
        "best_bid": snapshot.best_bid,
        "best_ask": snapshot.best_ask,
        "spread": snapshot.spread,
        "mid_price": snapshot.mid_price,
        "sequence_number": snapshot.sequence_number,
        "timestamp_ns": snapshot.timestamp_ns,
    }


def _proto_order_response_to_dict(resp: Any) -> dict:
    return {
        "order_id": resp.order_id,
        "client_order_id": resp.client_order_id,
        "status": resp.status,
        "rejection_reason": resp.rejection_reason,
        "rejection_message": resp.rejection_message,
        "filled_quantity": resp.filled_quantity,
        "remaining_quantity": resp.remaining_quantity,
        "avg_fill_price": resp.avg_fill_price,
        "trades": [
            {
                "trade_id": t.trade_id,
                "symbol": t.symbol,
                "price": t.price,
                "quantity": t.quantity,
                "buy_order_id": t.buy_order_id,
                "sell_order_id": t.sell_order_id,
                "buyer_user_id": t.buyer_user_id,
                "seller_user_id": t.seller_user_id,
                "timestamp_ns": t.timestamp_ns,
            }
            for t in resp.trades
        ],
        "timestamp_ns": resp.timestamp_ns,
        "matching_latency_ns": resp.matching_latency_ns,
    }


def _proto_market_stats_to_dict(stats: Any) -> dict:
    return {
        "symbol": stats.symbol,
        "last_price": stats.last_price,
        "open_price": stats.open_price,
        "high_price": stats.high_price,
        "low_price": stats.low_price,
        "close_price": stats.close_price,
        "volume": stats.volume,
        "vwap": stats.vwap,
        "spread": stats.spread,
        "order_imbalance": stats.order_imbalance,
        "bid_depth": stats.bid_depth,
        "ask_depth": stats.ask_depth,
        "trade_count": stats.trade_count,
        "timestamp_ns": stats.timestamp_ns,
        "is_halted": stats.is_halted,
        "circuit_breaker_limit": stats.circuit_breaker_limit,
    }


def _proto_engine_metrics_to_dict(m: Any) -> dict:
    symbol_metrics = [
        {
            "symbol": s.symbol,
            "order_count": s.order_count,
            "trade_count": s.trade_count,
            "volume": s.volume,
            "is_halted": s.is_halted,
        }
        for s in m.symbol_metrics
    ]
    return {
        "total_orders_received": m.total_orders_received,
        "total_orders_matched": m.total_orders_matched,
        "total_orders_cancelled": m.total_orders_cancelled,
        "total_trades_executed": m.total_trades_executed,
        "total_orders_rejected": m.total_orders_rejected,
        "orders_per_second": m.orders_per_second,
        "trades_per_second": m.trades_per_second,
        "p50_latency_ns": m.p50_latency_ns,
        "p95_latency_ns": m.p95_latency_ns,
        "p99_latency_ns": m.p99_latency_ns,
        "p999_latency_ns": m.p999_latency_ns,
        "order_book_size": m.order_book_size,
        "uptime_seconds": m.uptime_seconds,
        "symbol_metrics": symbol_metrics,
    }


# ── Mock fallbacks ────────────────────────────────────────────────────────────

_MOCK_ORDER_BOOK = {
    "symbol": "AAPL",
    "bids": [
        {"price": 150.00, "quantity": 100, "orders": 3},
        {"price": 149.95, "quantity": 200, "orders": 5},
    ],
    "asks": [
        {"price": 150.05, "quantity": 150, "orders": 2},
        {"price": 150.10, "quantity": 300, "orders": 4},
    ],
    "best_bid": 150.00,
    "best_ask": 150.05,
    "spread": 0.05,
    "mid_price": 150.025,
    "sequence_number": 0,
    "timestamp_ns": 0,
    "_mock": True,
}

_MOCK_METRICS = {
    "total_orders_received": 0,
    "total_orders_matched": 0,
    "total_orders_cancelled": 0,
    "total_trades_executed": 0,
    "total_orders_rejected": 0,
    "orders_per_second": 0.0,
    "trades_per_second": 0.0,
    "p50_latency_ns": 0.0,
    "p95_latency_ns": 0.0,
    "p99_latency_ns": 0.0,
    "p999_latency_ns": 0.0,
    "order_book_size": 0,
    "uptime_seconds": 0,
    "symbol_metrics": [],
    "_mock": True,
}


# ── Client ────────────────────────────────────────────────────────────────────


class AsyncGRPCClient:
    """Thread-pool–backed async gRPC client for the matching engine."""

    _MAX_RETRIES = 3
    _INITIAL_BACKOFF = 0.1  # seconds

    def __init__(self) -> None:
        self._channel: grpc.Channel | None = None
        self._stub: Any | None = None
        self._executor = ThreadPoolExecutor(max_workers=16, thread_name_prefix="grpc")
        self._loop: asyncio.AbstractEventLoop | None = None

    # ── Lifecycle ─────────────────────────────────────────────

    def connect(self) -> None:
        if not _STUBS_AVAILABLE:
            logger.warning("gRPC stubs unavailable – mock mode active")
            return
        target = settings.grpc_target
        logger.info("Connecting to gRPC matching engine at %s", target)
        self._channel = grpc.insecure_channel(
            target,
            options=[
                ("grpc.keepalive_time_ms", 30_000),
                ("grpc.keepalive_timeout_ms", 10_000),
                ("grpc.keepalive_permit_without_calls", True),
                ("grpc.max_receive_message_length", 64 * 1024 * 1024),
            ],
        )
        self._stub = pb2_grpc.ExchangeServiceStub(self._channel)
        self._loop = asyncio.get_event_loop()

    def close(self) -> None:
        if self._channel:
            self._channel.close()
        self._executor.shutdown(wait=False)

    # ── Internal dispatcher ───────────────────────────────────

    async def _call(self, method_name: str, request: Any, timeout: float = 5.0) -> Any:
        """Run a gRPC call in the thread-pool and apply retry/backoff."""
        if not _STUBS_AVAILABLE or self._stub is None:
            raise RuntimeError("gRPC stub not available")

        loop = asyncio.get_event_loop()
        backoff = self._INITIAL_BACKOFF

        for attempt in range(1, self._MAX_RETRIES + 1):
            start = time.monotonic()
            try:
                method = getattr(self._stub, method_name)
                result = await loop.run_in_executor(
                    self._executor, lambda: method(request, timeout=timeout)
                )
                elapsed = time.monotonic() - start
                grpc_call_duration_seconds.labels(method=method_name).observe(elapsed)
                grpc_calls_total.labels(method=method_name, status="ok").inc()
                return result
            except grpc.RpcError as exc:
                elapsed = time.monotonic() - start
                code = exc.code() if hasattr(exc, "code") else grpc.StatusCode.UNKNOWN
                grpc_calls_total.labels(method=method_name, status=code.name).inc()
                grpc_call_duration_seconds.labels(method=method_name).observe(elapsed)
                if code in _RETRYABLE and attempt < self._MAX_RETRIES:
                    logger.warning(
                        "gRPC %s attempt %d/%d failed (%s) – retrying in %.2fs",
                        method_name,
                        attempt,
                        self._MAX_RETRIES,
                        code.name,
                        backoff,
                    )
                    await asyncio.sleep(backoff)
                    backoff *= 2
                else:
                    raise

    # ── Public API ────────────────────────────────────────────

    async def submit_order(self, order_data: dict) -> dict:
        try:
            request = pb2.OrderRequest(
                client_order_id=order_data.get("client_order_id", ""),
                user_id=order_data["user_id"],
                symbol=order_data["symbol"],
                side=pb2.Side.Value(order_data["side"]),
                order_type=pb2.OrderType.Value(order_data["order_type"]),
                price=float(order_data.get("price") or 0),
                stop_price=float(order_data.get("stop_price") or 0),
                quantity=int(order_data["quantity"]),
                expire_time_ms=int(order_data.get("expire_time_ms") or 0),
                session_id=order_data.get("session_id", ""),
            )
            resp = await self._call("SubmitOrder", request)
            return _proto_order_response_to_dict(resp)
        except Exception as exc:
            logger.error("submit_order failed: %s", exc)
            return {
                "order_id": "",
                "status": 2,  # REJECTED
                "rejection_message": str(exc),
                "_mock": True,
            }

    async def cancel_order(self, order_id: str, user_id: str, symbol: str) -> dict:
        try:
            request = pb2.CancelRequest(
                order_id=order_id,
                user_id=user_id,
                symbol=symbol,
            )
            resp = await self._call("CancelOrder", request)
            return {
                "success": resp.success,
                "message": resp.message,
                "order_id": resp.order_id,
                "cancelled_quantity": resp.cancelled_quantity,
            }
        except Exception as exc:
            logger.error("cancel_order failed: %s", exc)
            return {"success": False, "message": str(exc), "order_id": order_id, "_mock": True}

    async def amend_order(self, order_id: str, user_id: str, new_price: float, new_quantity: int) -> dict:
        try:
            request = pb2.AmendRequest(
                order_id=order_id,
                user_id=user_id,
                new_price=new_price,
                new_quantity=new_quantity,
            )
            resp = await self._call("AmendOrder", request)
            return _proto_order_response_to_dict(resp)
        except Exception as exc:
            logger.error("amend_order failed: %s", exc)
            return {"order_id": order_id, "status": 2, "rejection_message": str(exc), "_mock": True}

    async def get_order_book(self, symbol: str, depth: int = 10) -> dict:
        try:
            request = pb2.OrderBookRequest(symbol=symbol, depth=depth)
            resp = await self._call("GetOrderBook", request)
            return _proto_order_book_to_dict(resp)
        except Exception as exc:
            logger.error("get_order_book failed: %s", exc)
            mock = dict(_MOCK_ORDER_BOOK)
            mock["symbol"] = symbol
            return mock

    async def get_market_stats(self, symbol: str) -> dict:
        try:
            request = pb2.MarketStatsRequest(symbol=symbol)
            resp = await self._call("GetMarketStats", request)
            return _proto_market_stats_to_dict(resp)
        except Exception as exc:
            logger.error("get_market_stats failed: %s", exc)
            return {
                "symbol": symbol,
                "last_price": 0.0,
                "vwap": 0.0,
                "spread": 0.0,
                "volume": 0,
                "is_halted": False,
                "_mock": True,
            }

    async def get_trades(self, symbol: str, limit: int = 50,
                         from_ns: int = 0, to_ns: int = 0) -> dict:
        try:
            request = pb2.TradeHistoryRequest(
                symbol=symbol,
                limit=limit,
                from_timestamp_ns=from_ns,
                to_timestamp_ns=to_ns,
            )
            resp = await self._call("GetTrades", request)
            return {
                "trades": [
                    {
                        "trade_id": t.trade_id,
                        "symbol": t.symbol,
                        "price": t.price,
                        "quantity": t.quantity,
                        "buy_order_id": t.buy_order_id,
                        "sell_order_id": t.sell_order_id,
                        "buyer_user_id": t.buyer_user_id,
                        "seller_user_id": t.seller_user_id,
                        "timestamp_ns": t.timestamp_ns,
                    }
                    for t in resp.trades
                ],
                "total_count": resp.total_count,
            }
        except Exception as exc:
            logger.error("get_trades failed: %s", exc)
            return {"trades": [], "total_count": 0, "_mock": True}

    async def get_engine_metrics(self) -> dict:
        try:
            resp = await self._call("GetEngineMetrics", pb2.Empty())
            metrics = _proto_engine_metrics_to_dict(resp)
            # Forward to Prometheus
            engine_p50_latency_ns.set(metrics["p50_latency_ns"])
            engine_p95_latency_ns.set(metrics["p95_latency_ns"])
            engine_p99_latency_ns.set(metrics["p99_latency_ns"])
            engine_p999_latency_ns.set(metrics["p999_latency_ns"])
            engine_orders_per_second.set(metrics["orders_per_second"])
            engine_trades_per_second.set(metrics["trades_per_second"])
            return metrics
        except Exception as exc:
            logger.error("get_engine_metrics failed: %s", exc)
            return _MOCK_METRICS

    async def ping(self) -> dict:
        try:
            resp = await self._call("Ping", pb2.Empty(), timeout=2.0)
            return {
                "message": resp.message,
                "timestamp_ns": resp.timestamp_ns,
                "version": resp.version,
            }
        except Exception as exc:
            return {"message": "engine unreachable", "error": str(exc), "_mock": True}

    async def pause_market(self, symbol: str, admin_id: str = "admin", reason: str = "") -> dict:
        try:
            request = pb2.MarketControlRequest(
                symbol=symbol, admin_id=admin_id, reason=reason
            )
            resp = await self._call("PauseMarket", request)
            return {
                "success": resp.success,
                "message": resp.message,
                "symbol": resp.symbol,
                "is_halted": resp.is_halted,
            }
        except Exception as exc:
            logger.error("pause_market failed: %s", exc)
            return {"success": False, "message": str(exc), "_mock": True}

    async def resume_market(self, symbol: str, admin_id: str = "admin", reason: str = "") -> dict:
        try:
            request = pb2.MarketControlRequest(
                symbol=symbol, admin_id=admin_id, reason=reason
            )
            resp = await self._call("ResumeMarket", request)
            return {
                "success": resp.success,
                "message": resp.message,
                "symbol": resp.symbol,
                "is_halted": resp.is_halted,
            }
        except Exception as exc:
            logger.error("resume_market failed: %s", exc)
            return {"success": False, "message": str(exc), "_mock": True}

    async def set_circuit_breaker(
        self, symbol: str, price_change_pct: float, window_seconds: int, enabled: bool
    ) -> dict:
        try:
            request = pb2.CircuitBreakerConfig(
                symbol=symbol,
                price_change_pct=price_change_pct,
                window_seconds=window_seconds,
                enabled=enabled,
            )
            resp = await self._call("SetCircuitBreakerLimit", request)
            return {"success": resp.success, "message": resp.message}
        except Exception as exc:
            logger.error("set_circuit_breaker failed: %s", exc)
            return {"success": False, "message": str(exc), "_mock": True}


# ── Singleton instance ────────────────────────────────────────────────────────
grpc_client = AsyncGRPCClient()
