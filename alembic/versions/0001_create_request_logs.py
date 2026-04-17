"""create request_logs table

Revision ID: 0001_create_request_logs
Revises:
Create Date: 2026-04-17 00:00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0001_create_request_logs"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "request_logs",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_request_logs_id", "request_logs", ["id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_request_logs_id", table_name="request_logs")
    op.drop_table("request_logs")
