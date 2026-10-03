"""coupons and order discounts

Revision ID: 0003
Revises: 0002
Create Date: 2025-12-08 09:05:27
"""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "coupons",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(32), nullable=False),
        sa.Column("percent_off", sa.Integer(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("percent_off BETWEEN 1 AND 100", name="ck_coupons_percent_off_range"),
        sa.UniqueConstraint("code", name="uq_coupons_code"),
    )
    op.add_column("orders", sa.Column("discount_cents", sa.BigInteger(), nullable=False, server_default="0"))
    op.add_column("orders", sa.Column("coupon_id", sa.Integer(), sa.ForeignKey("coupons.id")))


def downgrade() -> None:
    op.drop_column("orders", "coupon_id")
    op.drop_column("orders", "discount_cents")
    op.drop_table("coupons")
