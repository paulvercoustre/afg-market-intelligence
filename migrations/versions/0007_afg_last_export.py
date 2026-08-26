"""afg_last_export_year / afg_last_export_value_usd columns on indicators

Revision ID: 0007
Revises: 0006
Create Date: 2026-08-25
"""

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # afg_export_value_usd is pinned to trade_data_year so it stays
    # same-year-comparable with global_market_size_usd (market_share_pct,
    # afg_supplier_rank) -- including a genuine zero when Afghanistan simply
    # isn't in that year's partner breakdown. These two columns instead
    # record the most recent year (bounded, see AFG_LAST_EXPORT_FLOOR_YEAR in
    # etl/transform.py) that Afghanistan actually had any recorded export
    # value to this market, purely for display, so a current-year zero isn't
    # shown to the user as if no data ever existed.
    op.add_column("indicators", sa.Column("afg_last_export_year", sa.Integer))
    op.add_column("indicators", sa.Column("afg_last_export_value_usd", sa.Numeric(20, 2)))


def downgrade() -> None:
    op.drop_column("indicators", "afg_last_export_value_usd")
    op.drop_column("indicators", "afg_last_export_year")
