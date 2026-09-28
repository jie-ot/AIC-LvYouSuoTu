"""Travel discovery posts, explicit feedback and reader preferences."""

import sqlalchemy as sa
from alembic import op

revision = "a28d9f13b601"
down_revision = "f7a1c2d3e4f5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "discovery_posts",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("trip_id", sa.String(), nullable=True),
        sa.Column("request_id", sa.String(), nullable=False),
        sa.Column("author", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("destination", sa.String(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("recommendations", sa.Text(), nullable=False),
        sa.Column("pitfalls", sa.Text(), nullable=False),
        sa.Column("tags", sa.JSON(), nullable=False),
        sa.Column("photos", sa.JSON(), nullable=False),
        sa.Column("attachments", sa.JSON(), nullable=False),
        sa.Column("is_demo", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "request_id", name="uq_discovery_publish_request"),
    )
    op.create_index("ix_discovery_posts_user_id", "discovery_posts", ["user_id"])
    op.create_index("ix_discovery_posts_destination", "discovery_posts", ["destination"])
    op.create_index("idx_discovery_status_created", "discovery_posts", ["status", "created_at"])
    op.create_table(
        "discovery_feedback",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("post_id", sa.String(), sa.ForeignKey("discovery_posts.id"), nullable=False),
        sa.Column("saved", sa.Boolean(), nullable=False),
        sa.Column("dismissed", sa.Boolean(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "post_id", name="uq_discovery_feedback"),
    )
    op.create_index("ix_discovery_feedback_user_id", "discovery_feedback", ["user_id"])
    op.create_index("ix_discovery_feedback_post_id", "discovery_feedback", ["post_id"])
    op.create_table(
        "discovery_preferences",
        sa.Column("user_id", sa.String(), primary_key=True),
        sa.Column("recent_searches", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("discovery_feedback")
    op.drop_table("discovery_preferences")
    op.drop_table("discovery_posts")
