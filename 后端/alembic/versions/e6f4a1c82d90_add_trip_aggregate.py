"""add trip aggregate

Revision ID: e6f4a1c82d90
Revises: d37e61b14f2c
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Sequence
from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op

revision: str = "e6f4a1c82d90"
down_revision: str | None = "d37e61b14f2c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _new_trip_id() -> str:
    return f"trip_{uuid.uuid4().hex[:12]}"


def upgrade() -> None:
    op.create_table(
        "trips",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("location", sa.String(), nullable=True),
        sa.Column("start_date", sa.String(), nullable=True),
        sa.Column("end_date", sa.String(), nullable=True),
        sa.Column("date_label", sa.String(), nullable=False),
        sa.Column("cover_image", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_trips_user_id", "trips", ["user_id"])
    op.create_index("idx_trips_user_updated", "trips", ["user_id", "updated_at"])

    for table_name in ("plans", "postcard_groups", "reports", "generation_operations", "user_memory_events"):
        with op.batch_alter_table(table_name) as batch_op:
            batch_op.add_column(sa.Column("trip_id", sa.String(), nullable=True))
            batch_op.create_index(f"ix_{table_name}_trip_id", ["trip_id"])
            batch_op.create_foreign_key(
                f"fk_{table_name}_trip_id_trips",
                "trips",
                ["trip_id"],
                ["id"],
            )

    bind = op.get_bind()
    metadata = sa.MetaData()
    trips = sa.Table("trips", metadata, autoload_with=bind)
    groups = sa.Table("postcard_groups", metadata, autoload_with=bind)
    reports = sa.Table("reports", metadata, autoload_with=bind)
    plans = sa.Table("plans", metadata, autoload_with=bind)
    operations = sa.Table("generation_operations", metadata, autoload_with=bind)
    refs = sa.Table("file_asset_references", metadata, autoload_with=bind)

    group_rows = {row.id: row for row in bind.execute(sa.select(groups)).mappings()}
    report_rows = {row.id: row for row in bind.execute(sa.select(reports)).mappings()}
    plan_rows = {row.id: row for row in bind.execute(sa.select(plans)).mappings()}
    linked_groups: set[str] = set()
    linked_reports: set[str] = set()

    def add_trip(row: sa.RowMapping) -> str:
        trip_id = _new_trip_id()
        now = row.get("created_at") or datetime.now(timezone.utc).replace(tzinfo=None)
        location = str(row.get("location") or "").strip() or None
        if location in {"未知目的地", "未知地点"}:
            location = None
        bind.execute(trips.insert().values(
            id=trip_id,
            user_id=row["user_id"],
            title=location if location and location not in {"未知目的地", "未知地点"} else "旅行影像",
            location=location,
            start_date=row.get("start_date"),
            end_date=row.get("end_date"),
            date_label=str(row.get("date_label") or "日期待定"),
            cover_image=row.get("cover_image"),
            created_at=now,
            updated_at=row.get("updated_at") or now,
        ))
        return trip_id

    for operation in bind.execute(sa.select(operations)).mappings():
        payload = operation.get("response_json") or {}
        if not isinstance(payload, dict):
            continue
        group_id = ((payload.get("postcardGroup") or {}).get("id") if isinstance(payload.get("postcardGroup"), dict) else None)
        report_id = ((payload.get("report") or {}).get("id") if isinstance(payload.get("report"), dict) else None)
        candidates = [group_rows.get(group_id), report_rows.get(report_id)]
        candidates = [row for row in candidates if row is not None and row["user_id"] == operation["user_id"]]
        if not candidates:
            continue
        trip_id = add_trip(candidates[0])
        if group_id in group_rows and group_rows[group_id]["user_id"] == operation["user_id"]:
            bind.execute(groups.update().where(groups.c.id == group_id).values(trip_id=trip_id))
            linked_groups.add(group_id)
        if report_id in report_rows and report_rows[report_id]["user_id"] == operation["user_id"]:
            bind.execute(reports.update().where(reports.c.id == report_id).values(trip_id=trip_id))
            linked_reports.add(report_id)
        bind.execute(operations.update().where(operations.c.id == operation["id"]).values(trip_id=trip_id))

    photo_sets: dict[tuple[str, str], set[str]] = defaultdict(set)
    for ref in bind.execute(sa.select(refs).where(refs.c.role == "source_photo")).mappings():
        if ref["owner_type"] in {"postcard_group", "report"}:
            photo_sets[(ref["owner_type"], ref["owner_id"])].add(ref["asset_id"])
    groups_by_key: dict[tuple[str, frozenset[str]], list[str]] = defaultdict(list)
    reports_by_key: dict[tuple[str, frozenset[str]], list[str]] = defaultdict(list)
    for group_id, row in group_rows.items():
        photos = photo_sets.get(("postcard_group", group_id), set())
        if group_id not in linked_groups and photos:
            groups_by_key[(row["user_id"], frozenset(photos))].append(group_id)
    for report_id, row in report_rows.items():
        photos = photo_sets.get(("report", report_id), set())
        if report_id not in linked_reports and photos:
            reports_by_key[(row["user_id"], frozenset(photos))].append(report_id)
    for key, group_ids in groups_by_key.items():
        report_ids = reports_by_key.get(key, [])
        if len(group_ids) != 1 or len(report_ids) != 1:
            continue
        group_id, report_id = group_ids[0], report_ids[0]
        trip_id = add_trip(group_rows[group_id])
        bind.execute(groups.update().where(groups.c.id == group_id).values(trip_id=trip_id))
        bind.execute(reports.update().where(reports.c.id == report_id).values(trip_id=trip_id))
        linked_groups.add(group_id)
        linked_reports.add(report_id)

    for group_id, row in group_rows.items():
        if group_id not in linked_groups:
            bind.execute(groups.update().where(groups.c.id == group_id).values(trip_id=add_trip(row)))
    for report_id, row in report_rows.items():
        if report_id not in linked_reports:
            bind.execute(reports.update().where(reports.c.id == report_id).values(trip_id=add_trip(row)))
    for plan_id, row in plan_rows.items():
        bind.execute(plans.update().where(plans.c.id == plan_id).values(trip_id=add_trip(row)))


def downgrade() -> None:
    for table_name in ("user_memory_events", "generation_operations", "reports", "postcard_groups", "plans"):
        with op.batch_alter_table(table_name) as batch_op:
            batch_op.drop_constraint(f"fk_{table_name}_trip_id_trips", type_="foreignkey")
            batch_op.drop_index(f"ix_{table_name}_trip_id")
            batch_op.drop_column("trip_id")
    op.drop_index("idx_trips_user_updated", table_name="trips")
    op.drop_index("ix_trips_user_id", table_name="trips")
    op.drop_table("trips")
