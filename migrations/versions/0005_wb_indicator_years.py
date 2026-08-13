"""World Bank indicator year columns on indicators

Revision ID: 0005
Revises: 0004
Create Date: 2026-08-05
"""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The year each World Bank field's stored value was actually reported
    # for. World Bank indicators publish on different cycles (LPI is
    # triennial, WGI lags 1-2 years) and _latest_wb_context() already falls
    # back to the latest available year per field independently -- but
    # without these columns there was no way to tell, from the data alone,
    # how stale a given market's lpi_score/regulatory_quality/
    # political_stability actually is. Mirrors tariff_year (migration 0004),
    # which solves the same problem for WITS rates.
    op.add_column("indicators", sa.Column("lpi_score_year", sa.Integer))
    op.add_column("indicators", sa.Column("regulatory_quality_year", sa.Integer))
    op.add_column("indicators", sa.Column("political_stability_year", sa.Integer))


def downgrade() -> None:
    op.drop_column("indicators", "political_stability_year")
    op.drop_column("indicators", "regulatory_quality_year")
    op.drop_column("indicators", "lpi_score_year")
