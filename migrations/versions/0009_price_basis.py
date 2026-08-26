"""price_basis column on indicators

Revision ID: 0009
Revises: 0008
Create Date: 2026-08-25
"""

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # unit_price_usd/market_avg_price_usd are now computed on different
    # bases per product (net_weight_kg by default, or a native unit like m²
    # for carpets -- see config.NATIVE_UNIT_PRICE_BASES) -- without this
    # column there was no way to tell, from the data alone, what a stored
    # price figure is actually priced per.
    op.add_column("indicators", sa.Column("price_basis", sa.Text))


def downgrade() -> None:
    op.drop_column("indicators", "price_basis")
