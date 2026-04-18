"""add faq and mode fields

Revision ID: 0002_add_faq_and_mode_fields
Revises: 0001_create_request_logs
Create Date: 2026-04-17 00:00:01
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0002_add_faq_and_mode_fields"
down_revision: Union[str, None] = "0001_create_request_logs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("request_logs", sa.Column("mode", sa.String(length=32), nullable=True))

    op.create_table(
        "support_faq_entries",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False, server_default="manual"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_support_faq_entries_id", "support_faq_entries", ["id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_support_faq_entries_id", table_name="support_faq_entries")
    op.drop_table("support_faq_entries")
    op.drop_column("request_logs", "mode")
