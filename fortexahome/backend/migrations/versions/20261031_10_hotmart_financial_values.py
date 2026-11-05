"""Persist provider-reported offer and full price separately from catalog price.

Revision ID: 20261031_10
Revises: 20261031_09
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261031_10"
down_revision: Union[str, None] = "20261031_09"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("orders", sa.Column("provider_price_cents", sa.Integer(), nullable=True))
    op.add_column("orders", sa.Column("provider_price_currency", sa.String(length=3), nullable=True))
    op.add_column("orders", sa.Column("provider_full_price_cents", sa.Integer(), nullable=True))
    op.add_column("orders", sa.Column("provider_full_price_currency", sa.String(length=3), nullable=True))


def downgrade() -> None:
    op.drop_column("orders", "provider_full_price_currency")
    op.drop_column("orders", "provider_full_price_cents")
    op.drop_column("orders", "provider_price_currency")
    op.drop_column("orders", "provider_price_cents")
