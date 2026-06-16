"""Initial migration – create all ExchangeX tables.

Revision ID: 0001_initial
Revises:
Create Date: 2026-06-11 00:00:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── users ──────────────────────────────────────────────────────────────────
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("hashed_password", sa.String(length=255), nullable=False),
        sa.Column("balance", sa.Float(), nullable=False, server_default="100000.0"),
        sa.Column("is_admin", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_users_email"), "users", ["email"], unique=True)

    # ── orders ─────────────────────────────────────────────────────────────────
    op.create_table(
        "orders",
        sa.Column("id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("client_order_id", sa.String(length=128), nullable=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column(
            "side",
            sa.Enum("BUY", "SELL", name="sideenum"),
            nullable=False,
        ),
        sa.Column(
            "order_type",
            sa.Enum(
                "LIMIT", "MARKET", "STOP_LOSS", "STOP_LIMIT", "IOC", "FOK", "GTT",
                name="ordertypeenum",
            ),
            nullable=False,
        ),
        sa.Column("price", sa.Float(), nullable=True),
        sa.Column("stop_price", sa.Float(), nullable=True),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("filled_qty", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("avg_fill_price", sa.Float(), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "PENDING", "ACCEPTED", "REJECTED", "FILLED", "PARTIAL_FILL",
                "CANCELLED", "EXPIRED",
                name="orderstatusenum",
            ),
            nullable=False,
            server_default="PENDING",
        ),
        sa.Column("rejection_reason", sa.String(length=128), nullable=True),
        sa.Column("expire_time_ms", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_orders_user_id"), "orders", ["user_id"])
    op.create_index(op.f("ix_orders_symbol"), "orders", ["symbol"])
    op.create_index(op.f("ix_orders_status"), "orders", ["status"])
    op.create_index(op.f("ix_orders_created_at"), "orders", ["created_at"])
    op.create_index(op.f("ix_orders_client_order_id"), "orders", ["client_order_id"])

    # ── trades ─────────────────────────────────────────────────────────────────
    op.create_table(
        "trades",
        sa.Column("id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("engine_trade_id", sa.String(length=128), nullable=True),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("price", sa.Float(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("buy_order_id", sa.String(length=128), nullable=True),
        sa.Column("sell_order_id", sa.String(length=128), nullable=True),
        sa.Column("buyer_id", postgresql.UUID(as_uuid=False), nullable=True),
        sa.Column("seller_id", postgresql.UUID(as_uuid=False), nullable=True),
        sa.Column(
            "timestamp",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["buyer_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["seller_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_trades_symbol"), "trades", ["symbol"])
    op.create_index(op.f("ix_trades_timestamp"), "trades", ["timestamp"])
    op.create_index(op.f("ix_trades_buyer_id"), "trades", ["buyer_id"])
    op.create_index(op.f("ix_trades_seller_id"), "trades", ["seller_id"])
    op.create_index(op.f("ix_trades_engine_trade_id"), "trades", ["engine_trade_id"])
    op.create_index(op.f("ix_trades_buy_order_id"), "trades", ["buy_order_id"])
    op.create_index(op.f("ix_trades_sell_order_id"), "trades", ["sell_order_id"])

    # ── positions ──────────────────────────────────────────────────────────────
    op.create_table(
        "positions",
        sa.Column("id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("avg_cost", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_positions_user_id"), "positions", ["user_id"])
    op.create_index(op.f("ix_positions_symbol"), "positions", ["symbol"])

    # ── pnl ────────────────────────────────────────────────────────────────────
    op.create_table(
        "pnl",
        sa.Column("id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("realized_pnl", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("unrealized_pnl", sa.Float(), nullable=False, server_default="0.0"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_pnl_user_id"), "pnl", ["user_id"])
    op.create_index(op.f("ix_pnl_date"), "pnl", ["date"])

    # ── events ─────────────────────────────────────────────────────────────────
    op.create_table(
        "events",
        sa.Column("id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("payload", postgresql.JSON(astext_type=sa.Text()), nullable=False),
        sa.Column("sequence_num", sa.BigInteger(), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=True),
        sa.Column(
            "timestamp",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_events_event_type"), "events", ["event_type"])
    op.create_index(op.f("ix_events_sequence_num"), "events", ["sequence_num"])
    op.create_index(op.f("ix_events_symbol"), "events", ["symbol"])
    op.create_index(op.f("ix_events_timestamp"), "events", ["timestamp"])


def downgrade() -> None:
    op.drop_table("events")
    op.drop_table("pnl")
    op.drop_table("positions")
    op.drop_table("trades")
    op.drop_table("orders")
    op.drop_table("users")
    # Drop custom enum types
    sa.Enum(name="orderstatusenum").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="ordertypeenum").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="sideenum").drop(op.get_bind(), checkfirst=True)
