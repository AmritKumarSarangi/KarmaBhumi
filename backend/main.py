"""
main.py – FastAPI application entry point for ExchangeX backend.

Responsibilities:
  - Lifespan: connect/disconnect DB, gRPC, Kafka, Redis, start heartbeat
  - Register all API routers
  - CORS middleware (allow all origins for dev)
  - Prometheus metrics middleware
  - Structured JSON logging via structlog
  - /metrics endpoint (Prometheus scrape)
  - /api/health  liveness probe
  - /api/latency p50/p95/p99 stats forwarded from matching engine
"""
from __future__ import annotations

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import structlog
import uvicorn
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from config import settings
from db.database import engine
from db.models import Base
from grpc_client import grpc_client
from kafka.consumer import kafka_consumer
from monitoring.metrics import http_request_duration_seconds, http_requests_total

# ── Structured logging ────────────────────────────────────────────────────────

structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(
        getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)
    ),
    logger_factory=structlog.PrintLoggerFactory(),
)

log = structlog.get_logger()


# ── Lifespan ──────────────────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    log.info("ExchangeX backend starting up…")

    # ── Database ──────────────────────────────────────────────
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    log.info("Database tables ensured")

    # ── gRPC ──────────────────────────────────────────────────
    try:
        grpc_client.connect()
        log.info("gRPC client connected", target=settings.grpc_target)
    except Exception as exc:
        log.warning("gRPC connect failed – mock mode", error=str(exc))

    # ── Kafka ─────────────────────────────────────────────────
    try:
        await kafka_consumer.start()
        log.info("Kafka consumer started", brokers=settings.KAFKA_BROKERS)
    except Exception as exc:
        log.warning("Kafka consumer start failed", error=str(exc))

    # ── WebSocket heartbeat ───────────────────────────────────
    from api.websocket import manager

    heartbeat_task = asyncio.create_task(manager.heartbeat_loop(), name="ws-heartbeat")

    log.info("ExchangeX backend ready")
    yield  # ← app is running

    # ── Shutdown ──────────────────────────────────────────────
    log.info("ExchangeX backend shutting down…")
    heartbeat_task.cancel()
    try:
        await heartbeat_task
    except asyncio.CancelledError:
        pass

    await kafka_consumer.stop()
    grpc_client.close()
    await engine.dispose()
    log.info("Shutdown complete")


# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="ExchangeX API",
    description="High-performance stock exchange backend",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)

# ── CORS ──────────────────────────────────────────────────────────────────────

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Prometheus middleware ─────────────────────────────────────────────────────


@app.middleware("http")
async def prometheus_middleware(request: Request, call_next):
    start = time.monotonic()
    response: Response = await call_next(request)
    elapsed = time.monotonic() - start

    # Normalise path to avoid cardinality explosion
    path = request.url.path
    # Strip UUIDs / numeric IDs from path
    import re
    path = re.sub(r"/[0-9a-f-]{8,}", "/{id}", path)

    http_requests_total.labels(
        method=request.method,
        endpoint=path,
        status_code=str(response.status_code),
    ).inc()
    http_request_duration_seconds.labels(
        method=request.method,
        endpoint=path,
    ).observe(elapsed)

    return response


# ── Routers ───────────────────────────────────────────────────────────────────

from api.routes import auth, orders, market, portfolio, admin, replay, bots
from api.websocket import router as ws_router

app.include_router(auth.router)
app.include_router(orders.router)
app.include_router(market.router)
app.include_router(portfolio.router)
app.include_router(admin.router)
app.include_router(replay.router)
app.include_router(bots.router)
app.include_router(ws_router)


# ── Static endpoints ──────────────────────────────────────────────────────────


@app.get("/api/health", tags=["system"])
async def health() -> dict:
    ping = await grpc_client.ping()
    return {
        "status": "ok",
        "engine": ping.get("message", "unknown"),
        "mock_mode": ping.get("_mock", False),
    }


@app.get("/api/latency", tags=["system"])
async def latency_stats() -> dict:
    """Return p50/p95/p99 latency by scraping the matching engine Prometheus metrics."""
    import httpx
    import re as _re

    try:
        loop = asyncio.get_event_loop()
        resp = await loop.run_in_executor(
            None,
            lambda: httpx.get("http://matching-engine:8080/metrics", timeout=2.0)
        )
        text = resp.text

        # The C++ engine exposes pre-computed percentile gauges
        def get_gauge(name: str) -> float:
            m = _re.search(rf'^{_re.escape(name)}\s+([\d.e+\-]+)', text, _re.MULTILINE)
            return float(m.group(1)) if m else 0.0

        orders_m = _re.search(r'^exchange_orders_total\s+(\d+)', text, _re.MULTILINE)
        trades_m = _re.search(r'^exchange_trades_total\s+(\d+)', text, _re.MULTILINE)

        return {
            "p50_latency_ns": get_gauge("exchange_latency_p50_ns"),
            "p95_latency_ns": get_gauge("exchange_latency_p95_ns"),
            "p99_latency_ns": get_gauge("exchange_latency_p99_ns"),
            "p999_latency_ns": get_gauge("exchange_latency_p999_ns"),
            "orders_per_second": int(orders_m.group(1)) if orders_m else 0,
            "trades_per_second": int(trades_m.group(1)) if trades_m else 0,
            "total_orders": int(orders_m.group(1)) if orders_m else 0,
            "total_trades": int(trades_m.group(1)) if trades_m else 0,
            "mock": False,
        }
    except Exception as exc:
        log.warning("Failed to scrape matching engine metrics", error=str(exc))
        metrics = await grpc_client.get_engine_metrics()
        return {
            "p50_latency_ns": metrics.get("p50_latency_ns", 0),
            "p95_latency_ns": metrics.get("p95_latency_ns", 0),
            "p99_latency_ns": metrics.get("p99_latency_ns", 0),
            "p999_latency_ns": metrics.get("p999_latency_ns", 0),
            "orders_per_second": metrics.get("orders_per_second", 0),
            "trades_per_second": metrics.get("trades_per_second", 0),
            "mock": metrics.get("_mock", True),
        }



@app.get("/metrics", tags=["system"], include_in_schema=False)
async def prometheus_metrics() -> Response:
    data = generate_latest()
    return Response(content=data, media_type=CONTENT_TYPE_LATEST)


# ── Dev entrypoint ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=(settings.APP_ENV == "development"),
        log_level=settings.LOG_LEVEL.lower(),
    )
