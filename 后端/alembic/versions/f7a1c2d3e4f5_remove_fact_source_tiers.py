"""remove fact source tiers

Revision ID: f7a1c2d3e4f5
Revises: e6f4a1c82d90
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "f7a1c2d3e4f5"
down_revision: str | None = "e6f4a1c82d90"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("tool_call_logs") as batch_op:
        batch_op.drop_column("degraded_to_b")

    bind = op.get_bind()
    metadata = sa.MetaData()
    plans = sa.Table("plans", metadata, autoload_with=bind)
    for row in bind.execute(
        sa.select(plans.c.id, plans.c.itinerary_data)
    ).mappings():
        normalized, changed = _normalize_fact_status(row["itinerary_data"])
        if changed:
            bind.execute(
                plans.update()
                .where(plans.c.id == row["id"])
                .values(itinerary_data=normalized)
            )


def downgrade() -> None:
    with op.batch_alter_table("tool_call_logs") as batch_op:
        batch_op.add_column(
            sa.Column(
                "degraded_to_b",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )


def _normalize_fact_status(value: Any) -> tuple[Any, bool]:
    """Replace the removed source tier in every nested itinerary object."""
    if isinstance(value, list):
        changed = False
        normalized_items = []
        for item in value:
            normalized, item_changed = _normalize_fact_status(item)
            normalized_items.append(normalized)
            changed = changed or item_changed
        return normalized_items, changed
    if isinstance(value, dict):
        changed = False
        normalized_mapping: dict[str, Any] = {}
        for key, item in value.items():
            if key == "fact_status" and item == "reference":
                normalized_mapping[key] = "verified"
                changed = True
                continue
            normalized, item_changed = _normalize_fact_status(item)
            normalized_mapping[key] = normalized
            changed = changed or item_changed
        return normalized_mapping, changed
    return value, False
