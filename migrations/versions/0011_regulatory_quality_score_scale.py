"""widen regulatory_quality to fit the 0-100 WGI score scale

Revision ID: 0011
Revises: 0010
Create Date: 2026-08-27
"""

import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # regulatory_quality now comes from GOV_WGI_RQ.SC ("Governance score,
    # 0-100") instead of GOV_WGI_RQ.EST ("Governance estimate, approx -2.5
    # to +2.5") -- same reasoning as the political_stability switch in
    # migration 0010. The old NUMERIC(6,4) column (max 99.9999) would
    # silently overflow on any country scoring 100, so it's widened to
    # NUMERIC(6,3) (max 999.999) -- still enough precision, comfortably
    # above the new scale's ceiling.
    op.alter_column("market_context", "regulatory_quality", type_=sa.Numeric(6, 3))
    op.alter_column("indicators", "regulatory_quality", type_=sa.Numeric(6, 3))


def downgrade() -> None:
    op.alter_column("market_context", "regulatory_quality", type_=sa.Numeric(6, 4))
    op.alter_column("indicators", "regulatory_quality", type_=sa.Numeric(6, 4))
