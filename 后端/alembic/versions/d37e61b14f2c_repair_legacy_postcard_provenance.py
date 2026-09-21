"""repair legacy postcard provenance

Revision ID: d37e61b14f2c
Revises: c935d42a7e10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d37e61b14f2c"
down_revision: str | None = "c935d42a7e10"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    postcards = sa.table(
        "postcards",
        sa.column("source_asset_ids", sa.JSON()),
        sa.column("render_mode", sa.String()),
        sa.column("prompt_version", sa.String()),
    )
    op.execute(
        postcards.update()
        .where(
            sa.cast(postcards.c.source_asset_ids, sa.Text()) == "[]",
            postcards.c.render_mode == "ai_composite",
            postcards.c.prompt_version == "postcard-v3",
        )
        .values(render_mode="legacy", prompt_version="legacy-pre-v3")
    )


def downgrade() -> None:
    postcards = sa.table(
        "postcards",
        sa.column("source_asset_ids", sa.JSON()),
        sa.column("render_mode", sa.String()),
        sa.column("prompt_version", sa.String()),
    )
    op.execute(
        postcards.update()
        .where(
            postcards.c.render_mode == "legacy",
            postcards.c.prompt_version == "legacy-pre-v3",
        )
        .values(render_mode="ai_composite", prompt_version="postcard-v3")
    )
