"""tariff_year column on indicators

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-29
"""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The year the stored tariff_rate_pct was actually reported for by WITS.
    # This can differ from computed_for_year: WITS typically lags 2-3 years
    # behind trade data, so the fetch logic walks backward through years
    # until it finds a reported rate, then attaches that rate to whichever
    # indicator row computed_for_year represents. Without this column there
    # was no way to tell, from the data alone, which year a stored rate
    # actually came from.
    op.add_column("indicators", sa.Column("tariff_year", sa.Integer))


def downgrade() -> None:
    op.drop_column("indicators", "tariff_year")
