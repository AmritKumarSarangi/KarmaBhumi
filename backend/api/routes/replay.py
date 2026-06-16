"""
api/routes/replay.py – Event sourcing replay endpoints.

GET  /api/replay/{symbol}   – paginated event stream for a symbol
GET  /api/replay/events     – global paginated event log
WS   /ws/replay             – streams events at configurable speed
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect, status
from pydantic import BaseModel
from sqlalchemy import and_, asc, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.routes.auth import require_auth, _verify_token
from db.database import get_db
from db.models import Event, User

logger = logging.getLogger(__name__)

router = APIRouter(tags=["replay"])


# ── Schemas ───────────────────────────────────────────────────────────────────


class EventOut(BaseModel):
    id: str
    event_type: str
    symbol: str | None
    sequence_num: int
    payload: dict
    timestamp: datetime

    class Config:
        from_attributes = True


class EventPageResponse(BaseModel):
    events: list[EventOut]
    total: int
    page: int
    page_size: int


# ── Routes ────────────────────────────────────────────────────────────────────


@router.get("/api/replay/{symbol}", response_model=EventPageResponse)
async def replay_symbol(
    symbol: str,
    from_time: datetime | None = Query(default=None, alias="from"),
    to_time: datetime | None = Query(default=None, alias="to"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=1, le=1000),
    current_user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
) -> EventPageResponse:
    sym = symbol.upper()
    conditions = [Event.symbol == sym]

    if from_time:
        conditions.append(Event.timestamp >= from_time)
    if to_time:
        conditions.append(Event.timestamp <= to_time)

    all_q = select(Event).where(and_(*conditions))
    all_events = (await db.execute(all_q)).scalars().all()
    total = len(all_events)

    offset = (page - 1) * page_size
    q = (
        select(Event)
        .where(and_(*conditions))
        .order_by(asc(Event.sequence_num))
        .offset(offset)
        .limit(page_size)
    )
    events = (await db.execute(q)).scalars().all()

    return EventPageResponse(
        events=[EventOut.model_validate(e) for e in events],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/api/replay/events", response_model=EventPageResponse)
async def replay_all_events(
    event_type: str | None = Query(default=None),
    symbol: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=1, le=1000),
    current_user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
) -> EventPageResponse:
    conditions = []
    if event_type:
        conditions.append(Event.event_type == event_type)
    if symbol:
        conditions.append(Event.symbol == symbol.upper())

    base_q = select(Event)
    if conditions:
        base_q = base_q.where(and_(*conditions))

    all_events = (await db.execute(base_q)).scalars().all()
    total = len(all_events)

    offset = (page - 1) * page_size
    q = base_q.order_by(asc(Event.sequence_num)).offset(offset).limit(page_size)
    events = (await db.execute(q)).scalars().all()

    return EventPageResponse(
        events=[EventOut.model_validate(e) for e in events],
        total=total,
        page=page,
        page_size=page_size,
    )


# ── WebSocket replay ──────────────────────────────────────────────────────────


@router.websocket("/ws/replay")
async def ws_replay(
    websocket: WebSocket,
    token: str | None = Query(default=None),
    symbol: str | None = Query(default=None),
    speed: float = Query(default=1.0, ge=0.1, le=100.0),
) -> None:
    """Stream historical events at configurable speed multiplier."""
    import uuid
    user_id = None
    if token:
        user_id = _verify_token(token)
    
    if not user_id:
        user_id = f"anonymous_{uuid.uuid4()}"

    await websocket.accept()
    logger.info("WS replay started user=%s symbol=%s speed=%.1f", user_id, symbol, speed)

    from db.database import AsyncSessionLocal

    try:
        async with AsyncSessionLocal() as db:
            conditions = []
            if symbol:
                conditions.append(Event.symbol == symbol.upper())

            q = select(Event).order_by(asc(Event.sequence_num))
            if conditions:
                q = q.where(and_(*conditions))

            events = (await db.execute(q)).scalars().all()

        prev_ts: datetime | None = None
        for event in events:
            # Simulate real-time gaps between events (scaled by speed)
            if prev_ts is not None:
                gap = (event.timestamp - prev_ts).total_seconds()
                delay = gap / speed
                if 0 < delay < 60:  # cap delay at 60s
                    await asyncio.sleep(delay)
            prev_ts = event.timestamp

            payload = {
                "type": "replay_event",
                "data": {
                    "id": event.id,
                    "event_type": event.event_type,
                    "symbol": event.symbol,
                    "sequence_num": event.sequence_num,
                    "payload": event.payload,
                    "timestamp": event.timestamp.isoformat(),
                },
            }
            await websocket.send_text(json.dumps(payload, default=str))

        await websocket.send_text(json.dumps({"type": "replay_complete", "data": {}}))
        await websocket.close()

    except WebSocketDisconnect:
        logger.info("WS replay disconnected user=%s", user_id)
    except Exception as exc:
        logger.error("WS replay error: %s", exc)
        try:
            await websocket.close()
        except Exception:
            pass
