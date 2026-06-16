"""
api/routes/admin.py – Admin-only endpoints.

POST /api/admin/pause/{symbol}   – halt trading (circuit breaker)
POST /api/admin/resume/{symbol}  – resume trading
GET  /api/admin/metrics          – engine metrics
POST /api/admin/symbols          – register new tradeable symbol
GET  /api/admin/users            – list all users
PUT  /api/admin/limits           – update circuit breaker risk limits
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.routes.auth import require_admin
from db.database import get_db
from db.models import User
from grpc_client import grpc_client

router = APIRouter(prefix="/api/admin", tags=["admin"])


# ── Schemas ───────────────────────────────────────────────────────────────────


class AddSymbolRequest(BaseModel):
    symbol: str = Field(min_length=1, max_length=32)
    description: str = Field(default="")


class RiskLimitsRequest(BaseModel):
    symbol: str
    price_change_pct: float = Field(ge=0.1, le=100.0, description="Circuit breaker % threshold")
    window_seconds: int = Field(ge=10, le=86400)
    enabled: bool = True


class UserAdminOut(BaseModel):
    user_id: str
    email: str
    balance: float
    is_admin: bool
    created_at: datetime

    class Config:
        from_attributes = True


# ── Routes ────────────────────────────────────────────────────────────────────


@router.post("/pause/{symbol}")
async def pause_trading(
    symbol: str,
    reason: str = Query(default="Admin initiated halt"),
    admin_user: User = Depends(require_admin),
) -> dict:
    resp = await grpc_client.pause_market(
        symbol.upper(), admin_id=admin_user.id, reason=reason
    )
    if not resp.get("success") and not resp.get("_mock"):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=resp.get("message", "Failed to pause market"),
        )
    return {
        "symbol": symbol.upper(),
        "is_halted": True,
        "message": resp.get("message", f"Trading paused for {symbol}"),
        "admin": admin_user.email,
    }


@router.post("/resume/{symbol}")
async def resume_trading(
    symbol: str,
    reason: str = Query(default="Admin initiated resume"),
    admin_user: User = Depends(require_admin),
) -> dict:
    resp = await grpc_client.resume_market(
        symbol.upper(), admin_id=admin_user.id, reason=reason
    )
    if not resp.get("success") and not resp.get("_mock"):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=resp.get("message", "Failed to resume market"),
        )
    return {
        "symbol": symbol.upper(),
        "is_halted": False,
        "message": resp.get("message", f"Trading resumed for {symbol}"),
        "admin": admin_user.email,
    }


@router.get("/metrics")
async def engine_metrics(admin_user: User = Depends(require_admin)) -> dict:
    raw = await grpc_client.get_engine_metrics()
    # Convert nanoseconds to milliseconds and normalize field names for frontend
    ns_to_ms = lambda ns: round(ns / 1_000_000, 3) if ns else 0.0
    return {
        # Frontend expects these field names
        "latency_p50": ns_to_ms(raw.get("p50_latency_ns", 0)),
        "latency_p95": ns_to_ms(raw.get("p95_latency_ns", 0)),
        "latency_p99": ns_to_ms(raw.get("p99_latency_ns", 0)),
        "latency_p999": ns_to_ms(raw.get("p999_latency_ns", 0)),
        "orders_per_sec": raw.get("orders_per_second", 0),
        "trades_per_sec": raw.get("trades_per_second", 0),
        "active_websockets": 0,  # TODO: expose from WS manager
        "total_orders_today": raw.get("total_orders_received", 0),
        "total_trades_today": raw.get("total_trades_executed", 0),
        "queue_depth": 0,
        "cpu_usage": 0.0,
        "memory_usage": 0.0,
        # Also include raw data
        **raw,
    }


@router.post("/symbols", status_code=status.HTTP_201_CREATED)
async def add_symbol(
    body: AddSymbolRequest,
    admin_user: User = Depends(require_admin),
) -> dict:
    # In a real system this would persist to a symbols table
    # and notify the matching engine.  For now we validate and confirm.
    symbol = body.symbol.upper().strip()
    if len(symbol) < 1 or len(symbol) > 10:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid symbol")
    return {
        "symbol": symbol,
        "description": body.description,
        "created_by": admin_user.email,
        "status": "registered",
    }


@router.get("/users", response_model=list[UserAdminOut])
async def list_users(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    admin_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> list[UserAdminOut]:
    offset = (page - 1) * page_size
    result = await db.execute(
        select(User).order_by(User.created_at.desc()).offset(offset).limit(page_size)
    )
    users = result.scalars().all()
    return [
        UserAdminOut(
            user_id=u.id,
            email=u.email,
            balance=u.balance,
            is_admin=u.is_admin,
            created_at=u.created_at,
        )
        for u in users
    ]


@router.put("/limits")
async def update_risk_limits(
    body: RiskLimitsRequest,
    admin_user: User = Depends(require_admin),
) -> dict:
    resp = await grpc_client.set_circuit_breaker(
        symbol=body.symbol.upper(),
        price_change_pct=body.price_change_pct,
        window_seconds=body.window_seconds,
        enabled=body.enabled,
    )
    return {
        "symbol": body.symbol.upper(),
        "price_change_pct": body.price_change_pct,
        "window_seconds": body.window_seconds,
        "enabled": body.enabled,
        "engine_response": resp,
        "updated_by": admin_user.email,
    }


# Frontend expects /api/admin/risk-limits (PUT) — alias
@router.put("/risk-limits")
async def update_risk_limits_alias(
    body: RiskLimitsRequest,
    admin_user: User = Depends(require_admin),
) -> dict:
    return await update_risk_limits(body, admin_user)


@router.get("/circuit-breakers")
async def list_circuit_breakers(
    admin_user: User = Depends(require_admin),
) -> list:
    """Return circuit breaker status for all symbols."""
    symbols = ["AAPL", "GOOGL", "TSLA", "MSFT", "AMZN"]
    breakers = []
    for sym in symbols:
        # Try to get real status from engine, fall back to active
        try:
            stats = await grpc_client.get_market_stats(sym)
            is_halted = stats.get("is_halted", False)
        except Exception:
            is_halted = False
        breakers.append({
            "symbol": sym,
            "status": "halted" if is_halted else "active",
            "reason": None,
            "paused_at": None,
        })
    return breakers


@router.post("/circuit-breaker/{symbol}/pause")
async def pause_circuit_breaker(symbol: str, admin_user: User = Depends(require_admin)) -> dict:
    return await pause_trading(symbol, "Admin initiated halt", admin_user)


@router.post("/circuit-breaker/{symbol}/resume")
async def resume_circuit_breaker(symbol: str, admin_user: User = Depends(require_admin)) -> dict:
    return await resume_trading(symbol, "Admin initiated resume", admin_user)


@router.get("/activity-log")
async def activity_log(
    admin_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> list:
    """Return recent system events as activity log entries."""
    from db.models import Event
    from sqlalchemy import desc
    result = await db.execute(
        select(Event).order_by(desc(Event.timestamp)).limit(50)
    )
    events = result.scalars().all()
    return [
        {
            "timestamp": e.timestamp.isoformat() if e.timestamp else None,
            "event": e.event_type,
            "severity": "warning" if "REJECTED" in e.event_type or "RISK" in e.event_type else "info",
        }
        for e in events
    ]
