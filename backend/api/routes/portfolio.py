"""
api/routes/portfolio.py – User portfolio & PnL endpoints.

GET /api/portfolio           – positions + cash + equity + PnL
GET /api/portfolio/history   – daily PnL history
GET /api/portfolio/trades    – user's executed trades
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import and_, desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.routes.auth import require_auth
from db.database import get_db
from db.models import PnL, Position, Trade, User
from grpc_client import grpc_client

router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])


# ── Pydantic schemas ──────────────────────────────────────────────────────────


class PositionOut(BaseModel):
    symbol: str
    quantity: int
    avg_cost: float
    current_price: float
    market_value: float
    unrealized_pnl: float
    unrealized_pnl_pct: float
    updated_at: datetime

    class Config:
        from_attributes = True


class PortfolioOut(BaseModel):
    user_id: str
    cash_balance: float
    total_equity: float
    total_market_value: float
    total_unrealized_pnl: float
    total_realized_pnl: float
    positions: list[PositionOut]


class PnLHistoryPoint(BaseModel):
    date: str
    realized_pnl: float
    unrealized_pnl: float
    total_pnl: float


class TradeOut(BaseModel):
    id: str
    symbol: str
    price: float
    quantity: int
    buy_order_id: str | None
    sell_order_id: str | None
    timestamp: datetime

    class Config:
        from_attributes = True


# ── Routes ────────────────────────────────────────────────────────────────────


@router.get("", response_model=PortfolioOut)
async def get_portfolio(
    current_user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
) -> PortfolioOut:
    result = await db.execute(
        select(Position).where(Position.user_id == current_user.id)
    )
    positions = result.scalars().all()

    position_outs: list[PositionOut] = []
    total_market_value = 0.0
    total_unrealized_pnl = 0.0

    for pos in positions:
        if pos.quantity == 0:
            continue
        # Fetch current price from gRPC
        stats = await grpc_client.get_market_stats(pos.symbol)
        current_price = stats.get("last_price", pos.avg_cost)
        market_value = current_price * pos.quantity
        cost_basis = pos.avg_cost * pos.quantity
        unreal_pnl = market_value - cost_basis
        unreal_pct = (unreal_pnl / cost_basis * 100) if cost_basis else 0.0

        total_market_value += market_value
        total_unrealized_pnl += unreal_pnl

        position_outs.append(
            PositionOut(
                symbol=pos.symbol,
                quantity=pos.quantity,
                avg_cost=pos.avg_cost,
                current_price=current_price,
                market_value=market_value,
                unrealized_pnl=unreal_pnl,
                unrealized_pnl_pct=unreal_pct,
                updated_at=pos.updated_at,
            )
        )

    # Sum realized PnL from PnL table
    pnl_result = await db.execute(
        select(PnL).where(PnL.user_id == current_user.id)
    )
    pnl_records = pnl_result.scalars().all()
    total_realized_pnl = sum(r.realized_pnl for r in pnl_records)

    total_equity = current_user.balance + total_market_value

    return PortfolioOut(
        user_id=current_user.id,
        cash_balance=current_user.balance,
        total_equity=total_equity,
        total_market_value=total_market_value,
        total_unrealized_pnl=total_unrealized_pnl,
        total_realized_pnl=total_realized_pnl,
        positions=position_outs,
    )


@router.get("/history", response_model=list[PnLHistoryPoint])
async def get_pnl_history(
    days: int = Query(default=30, ge=1, le=365),
    current_user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
) -> list[PnLHistoryPoint]:
    result = await db.execute(
        select(PnL)
        .where(PnL.user_id == current_user.id)
        .order_by(PnL.date.asc())
        .limit(days)
    )
    records = result.scalars().all()
    return [
        PnLHistoryPoint(
            date=r.date.isoformat(),
            realized_pnl=r.realized_pnl,
            unrealized_pnl=r.unrealized_pnl,
            total_pnl=r.realized_pnl + r.unrealized_pnl,
        )
        for r in records
    ]


@router.get("/trades", response_model=list[TradeOut])
async def get_portfolio_trades(
    symbol: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    current_user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
) -> list[TradeOut]:
    from sqlalchemy import or_

    conditions = [
        or_(Trade.buyer_id == current_user.id, Trade.seller_id == current_user.id)
    ]
    if symbol:
        conditions.append(Trade.symbol == symbol.upper())

    result = await db.execute(
        select(Trade)
        .where(and_(*conditions))
        .order_by(desc(Trade.timestamp))
        .limit(limit)
    )
    trades = result.scalars().all()
    return [TradeOut.model_validate(t) for t in trades]
