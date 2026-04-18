"""add gateway entities for router mvp

Revision ID: 0004_add_gateway_entities
Revises: 0003_add_support_quality_logs
Create Date: 2026-04-18 00:10:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0004_add_gateway_entities"
down_revision: Union[str, None] = "0003_add_support_quality_logs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "gateway_users",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("api_key", sa.String(length=128), nullable=False),
        sa.Column("plan", sa.String(length=64), nullable=False, server_default="starter"),
        sa.Column("tokens_balance", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_gateway_users_id", "gateway_users", ["id"], unique=False)
    op.create_index("ux_gateway_users_email", "gateway_users", ["email"], unique=True)
    op.create_index("ux_gateway_users_api_key", "gateway_users", ["api_key"], unique=True)

    op.create_table(
        "ai_models_catalog",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("model_key", sa.String(length=128), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("target_model", sa.String(length=255), nullable=False),
        sa.Column("price_per_1k_tokens", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_ai_models_catalog_id", "ai_models_catalog", ["id"], unique=False)
    op.create_index("ux_ai_models_catalog_model_key", "ai_models_catalog", ["model_key"], unique=True)

    op.create_table(
        "gateway_usage_logs",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("model_key", sa.String(length=128), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completion_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cost_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("success", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["gateway_users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_gateway_usage_logs_id", "gateway_usage_logs", ["id"], unique=False)
    op.create_index("ix_gateway_usage_logs_user_id", "gateway_usage_logs", ["user_id"], unique=False)

    op.execute(
        """
        INSERT INTO ai_models_catalog
        (model_key, display_name, provider, target_model, price_per_1k_tokens, is_active)
        VALUES
        ('local-qwen', 'Local Qwen 2.5 3B', 'ollama', 'qwen2.5:3b', 1.0, true),
        ('local-llama', 'Local Llama 3.2', 'ollama', 'llama3.2:3b', 1.2, true),
        ('chatgpt-proxy', 'ChatGPT Proxy', 'openai-proxy', 'gpt-4o-mini', 3.0, true)
        """
    )


def downgrade() -> None:
    op.drop_index("ix_gateway_usage_logs_user_id", table_name="gateway_usage_logs")
    op.drop_index("ix_gateway_usage_logs_id", table_name="gateway_usage_logs")
    op.drop_table("gateway_usage_logs")

    op.drop_index("ux_ai_models_catalog_model_key", table_name="ai_models_catalog")
    op.drop_index("ix_ai_models_catalog_id", table_name="ai_models_catalog")
    op.drop_table("ai_models_catalog")

    op.drop_index("ux_gateway_users_api_key", table_name="gateway_users")
    op.drop_index("ux_gateway_users_email", table_name="gateway_users")
    op.drop_index("ix_gateway_users_id", table_name="gateway_users")
    op.drop_table("gateway_users")
