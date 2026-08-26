"""quantity_unit column on competitor_flows

Revision ID: 0008
Revises: 0007
Create Date: 2026-08-25
"""

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # trade_flows already has quantity_unit (0001_initial_schema); competitor_flows
    # never did, even though the same Comtrade qtyUnitCode/qtyUnitAbbr fields are
    # available for supplier rows -- this brings it in line so per-supplier unit
    # labels can be compared for consistency (kg vs m^2 vs pieces, ...) instead of
    # only ever being resolvable for Afghanistan's own flow.
    op.add_column("competitor_flows", sa.Column("quantity_unit", sa.Text))


def downgrade() -> None:
    op.drop_column("competitor_flows", "quantity_unit")
