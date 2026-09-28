"""Persist versioned travel semantic vectors."""

import sqlalchemy as sa
from alembic import op

revision = "c91e52fa7048"
down_revision = "a28d9f13b601"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "discovery_embeddings",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("scope", sa.String(), nullable=False),
        sa.Column("source_id", sa.String(), nullable=False),
        sa.Column("model_key", sa.String(), nullable=False),
        sa.Column("content_hash", sa.String(), nullable=False),
        sa.Column("vector", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_discovery_embeddings_scope", "discovery_embeddings", ["scope"])
    op.create_index("ix_discovery_embeddings_model_key", "discovery_embeddings", ["model_key"])


def downgrade() -> None:
    op.drop_table("discovery_embeddings")
