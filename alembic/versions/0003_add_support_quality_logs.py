"""add support faq query metrics table

Revision ID: 0003_add_support_quality_logs
Revises: 0002_add_faq_and_mode_fields
Create Date: 2026-04-18 00:00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0003_add_support_quality_logs"
down_revision: Union[str, None] = "0002_add_faq_and_mode_fields"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "support_faq_query_metrics",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("normalized_question", sa.String(length=512), nullable=False),
        sa.Column("matched_items", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("relevance_avg", sa.Float(), nullable=False, server_default="0"),
        sa.Column("relevance_max", sa.Float(), nullable=False, server_default="0"),
        sa.Column("zero_match", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("source_mode", sa.String(length=32), nullable=False, server_default="support_faq"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index(
        "ix_support_faq_query_metrics_id",
        "support_faq_query_metrics",
        ["id"],
        unique=False,
    )
    op.create_index(
        "ix_support_faq_query_metrics_normalized_question",
        "support_faq_query_metrics",
        ["normalized_question"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_support_faq_query_metrics_normalized_question",
        table_name="support_faq_query_metrics",
    )
    op.drop_index("ix_support_faq_query_metrics_id", table_name="support_faq_query_metrics")
    op.drop_table("support_faq_query_metrics")
