"""
api/routes/orders.py – Order management endpoints.

POST   /api/orders                   – place order via gRPC
DELETE /api/orders/{order_id}        – cancel order
GET    /api/orders                   – list user's orders (paginated)
GET    /api/orders/{order_id}        – single order detail
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.routes.auth import require_auth
from db.database import get_db
from db.models import Order, OrderStatusEnum, OrderTypeEnum, SideEnum, User, Event
from grpc_client import grpc_client
from monitoring.metrics import (
    orders_submitted_total,
    orders_filled_total,
    orders_rejected_total,
    orders_cancelled_total,
    trades_executed_total,
    trade_volume_total,
)

router = APIRouter(prefix="/api/orders", tags=["orders"])


# ── Pydantic schemas ──────────────────────────────────────────────────────────


class PlaceOrderRequest(BaseModel):
    symbol: str = Field(min_length=1, max_length=32)
    side: SideEnum
    order_type: OrderTypeEnum
    quantity: int = Field(gt=0, le=1_000_000)
    price: float | None = Field(default=None, ge=0)
    stop_price: float | None = Field(default=None, ge=0)
    expire_time_ms: int | None = None
    client_order_id: str | None = None


class OrderOut(BaseModel):
    order_id: str
    client_order_id: str | None
    user_id: str
    symbol: str
    side: SideEnum
    order_type: OrderTypeEnum
    price: float | None
    stop_price: float | None
    quantity: int
    filled_qty: int
    avg_fill_price: float | None
    status: OrderStatusEnum
    rejection_reason: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True, "populate_by_name": True}

    @classmethod
    def model_validate(cls, obj, **kwargs):
        """Handle DB model where primary key is 'id' not 'order_id'."""
        if hasattr(obj, 'id') and not hasattr(obj, 'order_id'):
            from pydantic import model_validator
            data = {
                'order_id': obj.id,
                'client_order_id': obj.client_order_id,
                'user_id': obj.user_id,
                'symbol': obj.symbol,
                'side': obj.side,
                'order_type': obj.order_type,
                'price': obj.price,
                'stop_price': obj.stop_price,
                'quantity': obj.quantity,
                'filled_qty': obj.filled_qty,
                'avg_fill_price': obj.avg_fill_price,
                'status': obj.status,
                'rejection_reason': obj.rejection_reason,
                'created_at': obj.created_at,
                'updated_at': obj.updated_at,
            }
            return cls(**data)
        return super().model_validate(obj, **kwargs)


class PlaceOrderResponse(BaseModel):
    order: OrderOut
    engine_response: dict


class OrdersListResponse(BaseModel):
    orders: list[OrderOut]
    total: int
    page: int
    page_size: int


# ── Routes ────────────────────────────────────────────────────────────────────


@router.post("", response_model=PlaceOrderResponse, status_code=status.HTTP_201_CREATED)
async def place_order(
    body: PlaceOrderRequest,
    current_user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
) -> PlaceOrderResponse:
    symbol = body.symbol.upper()

    # Validate: LIMIT orders must have price
    if body.order_type in (OrderTypeEnum.LIMIT, OrderTypeEnum.STOP_LIMIT) and not body.price:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Price required for LIMIT/STOP_LIMIT orders",
        )

    order_id = str(uuid.uuid4())
    client_order_id = body.client_order_id or order_id

    # Submit to matching engine
    engine_resp = await grpc_client.submit_order(
        {
            "client_order_id": client_order_id,
            "user_id": current_user.id,
            "symbol": symbol,
            "side": body.side.value,
            "order_type": body.order_type.value,
            "price": body.price,
            "stop_price": body.stop_price,
            "quantity": body.quantity,
            "expire_time_ms": body.expire_time_ms,
            "session_id": "",
        }
    )

    # Map engine status to DB enum
    status_map = {
        1: OrderStatusEnum.ACCEPTED,
        2: OrderStatusEnum.REJECTED,
        3: OrderStatusEnum.FILLED,
        4: OrderStatusEnum.PARTIAL_FILL,
        5: OrderStatusEnum.CANCELLED,
        6: OrderStatusEnum.EXPIRED,
        7: OrderStatusEnum.PENDING,
    }
    engine_status = engine_resp.get("status", 7)
    db_status = status_map.get(int(engine_status), OrderStatusEnum.PENDING)

    # Persist order to DB (use engine-assigned ID in client_order_id field to keep track)
    engine_order_id = engine_resp.get("order_id")
    db_order = Order(
        id=order_id,
        client_order_id=engine_order_id if engine_order_id else client_order_id,
        user_id=current_user.id,
        symbol=symbol,
        side=body.side,
        order_type=body.order_type,
        price=body.price,
        stop_price=body.stop_price,
        quantity=body.quantity,
        filled_qty=int(engine_resp.get("filled_quantity", 0)),
        avg_fill_price=engine_resp.get("avg_fill_price"),
        status=db_status,
        rejection_reason=engine_resp.get("rejection_message"),
        expire_time_ms=body.expire_time_ms,
    )
    db.add(db_order)

    # Event sourcing
    seq = int(datetime.now(timezone.utc).timestamp() * 1_000_000)
    event = Event(
        event_type="ORDER_SUBMITTED",
        payload={
            "order_id": db_order.id,
            "symbol": symbol,
            "side": body.side.value,
            "order_type": body.order_type.value,
            "quantity": body.quantity,
            "price": body.price,
            "user_id": current_user.id,
            "engine_response": engine_resp,
        },
        sequence_num=seq,
        symbol=symbol,
    )
    db.add(event)
    await db.flush()

    # Prometheus
    orders_submitted_total.labels(
        symbol=symbol, order_type=body.order_type.value, side=body.side.value
    ).inc()
    if db_status == OrderStatusEnum.FILLED:
        orders_filled_total.labels(symbol=symbol).inc()
    elif db_status == OrderStatusEnum.REJECTED:
        orders_rejected_total.labels(
            symbol=symbol, reason=engine_resp.get("rejection_message", "unknown")
        ).inc()
    for trade in engine_resp.get("trades", []):
        trades_executed_total.labels(symbol=symbol).inc()
        trade_volume_total.labels(symbol=symbol).inc(
            float(trade.get("price", 0)) * float(trade.get("quantity", 0))
        )

    return PlaceOrderResponse(order=OrderOut.model_validate(db_order), engine_response=engine_resp)


@router.delete("/{order_id}", status_code=status.HTTP_200_OK)
async def cancel_order(
    order_id: str,
    current_user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
) -> dict:
    result = await db.execute(
        select(Order).where(
            and_(Order.id == order_id, Order.user_id == current_user.id)
        )
    )
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")

    if order.status in (OrderStatusEnum.FILLED, OrderStatusEnum.CANCELLED, OrderStatusEnum.EXPIRED):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Order cannot be cancelled in status {order.status.value}",
        )

    engine_resp = await grpc_client.cancel_order(order.client_order_id or order.id, current_user.id, order.symbol)

    if engine_resp.get("success", False) or engine_resp.get("_mock"):
        order.status = OrderStatusEnum.CANCELLED
        order.updated_at = datetime.now(timezone.utc)
        seq = int(datetime.now(timezone.utc).timestamp() * 1_000_000)
        event = Event(
            event_type="ORDER_CANCELLED",
            payload={"order_id": order_id, "user_id": current_user.id, "symbol": order.symbol},
            sequence_num=seq,
            symbol=order.symbol,
        )
        db.add(event)
        await db.flush()
        orders_cancelled_total.labels(symbol=order.symbol).inc()

    return {
        "order_id": order_id,
        "success": engine_resp.get("success", False),
        "message": engine_resp.get("message", ""),
        "cancelled_quantity": engine_resp.get("cancelled_quantity", 0),
    }


@router.get("", response_model=OrdersListResponse)
async def list_orders(
    symbol: str | None = Query(default=None),
    order_status: OrderStatusEnum | None = Query(default=None, alias="status"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    current_user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
) -> OrdersListResponse:
    conditions = [Order.user_id == current_user.id]
    if symbol:
        conditions.append(Order.symbol == symbol.upper())
    if order_status:
        conditions.append(Order.status == order_status)

    count_q = select(Order).where(and_(*conditions))
    all_orders = (await db.execute(count_q)).scalars().all()
    total = len(all_orders)

    offset = (page - 1) * page_size
    q = (
        select(Order)
        .where(and_(*conditions))
        .order_by(Order.created_at.desc())
        .offset(offset)
        .limit(page_size)
    )
    orders = (await db.execute(q)).scalars().all()

    return OrdersListResponse(
        orders=[OrderOut.model_validate(o) for o in orders],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{order_id}", response_model=OrderOut)
async def get_order(
    order_id: str,
    current_user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
) -> OrderOut:
    result = await db.execute(
        select(Order).where(
            and_(Order.id == order_id, Order.user_id == current_user.id)
        )
    )
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
    return OrderOut.model_validate(order)
