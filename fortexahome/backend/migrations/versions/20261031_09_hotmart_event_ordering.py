"""Persist provider event time and deterministic state precedence.

Revision ID: 20261031_09
Revises: 20261031_08
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261031_09"
down_revision: Union[str, None] = "20261031_08"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("payment_events", sa.Column("provider_event_created_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("payment_events", sa.Column("state_priority", sa.SmallInteger(), nullable=False, server_default="0"))
    op.create_index(
        "ix_payment_events_order_provider_time",
        "payment_events",
        ["order_id", "provider_event_created_at", "state_priority"],
    )


def downgrade() -> None:
    op.drop_index("ix_payment_events_order_provider_time", table_name="payment_events")
    op.drop_column("payment_events", "state_priority")
    op.drop_column("payment_events", "provider_event_created_at")
