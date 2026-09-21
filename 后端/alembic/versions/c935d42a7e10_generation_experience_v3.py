"""generation experience v3

Revision ID: c935d42a7e10
Revises: b824c31f5a21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c935d42a7e10"
down_revision: str | None = "b824c31f5a21"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("user_memory_events") as batch_op:
        batch_op.add_column(sa.Column("event_key", sa.String(), nullable=True))
        batch_op.create_index("uq_user_memory_events_event_key", ["event_key"], unique=True)
    with op.batch_alter_table("postcards") as batch_op:
        batch_op.add_column(sa.Column("source_asset_ids", sa.JSON(), nullable=False, server_default="[]"))
        batch_op.add_column(sa.Column("render_mode", sa.String(), nullable=False, server_default="ai_composite"))
        batch_op.add_column(sa.Column("prompt_version", sa.String(), nullable=False, server_default="postcard-v3"))

    op.create_table(
        "generation_operations",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("client_request_id", sa.String(), nullable=False),
        sa.Column("request_hash", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("postcard_status", sa.String(), nullable=False),
        sa.Column("report_status", sa.String(), nullable=False),
        sa.Column("memory_status", sa.String(), nullable=False),
        sa.Column("response_json", sa.JSON(), nullable=True),
        sa.Column("pending_memory_payload", sa.JSON(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "client_request_id", name="uq_generation_operation_user_request"),
    )
    op.create_index("ix_generation_operations_user_id", "generation_operations", ["user_id"])
    op.create_index(
        "idx_generation_operations_user_created",
        "generation_operations",
        ["user_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("idx_generation_operations_user_created", table_name="generation_operations")
    op.drop_index("ix_generation_operations_user_id", table_name="generation_operations")
    op.drop_table("generation_operations")
    with op.batch_alter_table("user_memory_events") as batch_op:
        batch_op.drop_index("uq_user_memory_events_event_key")
        batch_op.drop_column("event_key")
    with op.batch_alter_table("postcards") as batch_op:
        batch_op.drop_column("prompt_version")
        batch_op.drop_column("render_mode")
        batch_op.drop_column("source_asset_ids")
