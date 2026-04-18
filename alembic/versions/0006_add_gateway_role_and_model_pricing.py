"""add gateway user role and model pricing mode

Revision ID: 0006_add_gateway_role_and_model_pricing
Revises: 0005_add_gateway_balance_audit_logs
Create Date: 2026-04-18 02:10:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0006_add_gateway_role_and_model_pricing"
down_revision: Union[str, None] = "0005_add_gateway_balance_audit_logs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "gateway_users",
        sa.Column("role", sa.String(length=32), nullable=False, server_default="user"),
    )
    op.add_column(
        "ai_models_catalog",
        sa.Column("external_price_per_1k_tokens", sa.Float(), nullable=True),
    )
    op.add_column(
        "ai_models_catalog",
        sa.Column("markup_percent", sa.Float(), nullable=False, server_default="0"),
    )

    op.execute(
        """
        UPDATE ai_models_catalog
        SET
            external_price_per_1k_tokens = CASE
                WHEN provider = 'openai' THEN 6.0
                ELSE NULL
            END,
            markup_percent = CASE
                WHEN provider = 'openai' THEN 25.0
                ELSE 0
            END
        """
    )


def downgrade() -> None:
    op.drop_column("ai_models_catalog", "markup_percent")
    op.drop_column("ai_models_catalog", "external_price_per_1k_tokens")
    op.drop_column("gateway_users", "role")
