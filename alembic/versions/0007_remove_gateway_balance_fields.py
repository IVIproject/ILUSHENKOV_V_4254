"""remove gateway balance fields and audit table

Revision ID: 0007_remove_gateway_balance_fields
Revises: 0006_add_gateway_role_and_model_pricing
Create Date: 2026-04-18 23:35:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0007_remove_gateway_balance_fields"
down_revision: Union[str, None] = "0006_add_gateway_role_and_model_pricing"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_index("ix_gateway_balance_audit_logs_user_id", table_name="gateway_balance_audit_logs")
    op.drop_index("ix_gateway_balance_audit_logs_id", table_name="gateway_balance_audit_logs")
    op.drop_table("gateway_balance_audit_logs")

    op.drop_column("gateway_users", "tokens_balance")
    op.drop_column("gateway_users", "plan")


def downgrade() -> None:
    op.add_column(
        "gateway_users",
        sa.Column("plan", sa.String(length=64), nullable=False, server_default="starter"),
    )
    op.add_column(
        "gateway_users",
        sa.Column("tokens_balance", sa.Integer(), nullable=False, server_default="0"),
    )

    op.create_table(
        "gateway_balance_audit_logs",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("delta_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("balance_before", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("balance_after", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("actor", sa.String(length=32), nullable=False, server_default="system"),
        sa.Column("actor_reference", sa.String(length=128), nullable=True),
        sa.Column("reason", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["gateway_users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_gateway_balance_audit_logs_id", "gateway_balance_audit_logs", ["id"], unique=False)
    op.create_index(
        "ix_gateway_balance_audit_logs_user_id",
        "gateway_balance_audit_logs",
        ["user_id"],
        unique=False,
    )
