"""widen political_stability to fit the 0-100 WGI score scale

Revision ID: 0010
Revises: 0009
Create Date: 2026-08-27
"""

import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # political_stability now comes from GOV_WGI_PV.SC ("Governance score,
    # 0-100") instead of GOV_WGI_PV.EST ("Governance estimate, approx -2.5
    # to +2.5") -- a plain 0-100 range is much clearer to reason about and
    # display than a signed, roughly-normal estimate. The old NUMERIC(6,4)
    # column (max 99.9999) would silently overflow on any country scoring
    # 100, so it's widened to NUMERIC(6,3) (max 999.999) -- still enough
    # precision, comfortably above the new scale's ceiling.
    op.alter_column("market_context", "political_stability", type_=sa.Numeric(6, 3))
    op.alter_column("indicators", "political_stability", type_=sa.Numeric(6, 3))


def downgrade() -> None:
    op.alter_column("market_context", "political_stability", type_=sa.Numeric(6, 4))
    op.alter_column("indicators", "political_stability", type_=sa.Numeric(6, 4))
