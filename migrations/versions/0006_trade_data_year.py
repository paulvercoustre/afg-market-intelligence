"""trade_data_year column on indicators

Revision ID: 0006
Revises: 0005
Create Date: 2026-08-14
"""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The year the stored trade fields (global_market_size_usd,
    # afg_export_value_usd, market_share_pct, unit_price_usd,
    # market_avg_price_usd, price_vs_market_pct, price_competitiveness,
    # afg_supplier_rank) were actually reported for. These previously always
    # targeted computed_for_year exactly with no fallback -- a market whose
    # Comtrade submission for that year hasn't landed yet would silently
    # come back with empty trade fields (and a correspondingly depressed
    # score) instead of reusing its own last known year, unlike the World
    # Bank fields which already fall back via _latest_wb_context(). This
    # column records which year the fallback actually used, the same idea
    # as tariff_year/lpi_score_year applied to trade data.
    op.add_column("indicators", sa.Column("trade_data_year", sa.Integer))


def downgrade() -> None:
    op.drop_column("indicators", "trade_data_year")
