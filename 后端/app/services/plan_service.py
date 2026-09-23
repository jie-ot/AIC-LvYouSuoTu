"""Plan business service: list / save / update / delete.

Master flows: 《任务详细流程规范》四、八、九、十二. On save/update the backend
extracts destination/start/end from `trip_info`, generates `dateLabel` itself,
renders Markdown `content` via Jinja2 (never the model), writes in a short
transaction. AI-authored itinerary output is deliberately not used as memory
evidence; users confirm durable constraints in the travel-memory interface.
"""

from __future__ import annotations

import logging

from sqlmodel import Session, select

from app.core.exceptions import NotFoundError
from app.db.session import session_scope
from app.models import dto
from app.models.itinerary import ItineraryData
from app.models.plan import Plan as PlanEntity
from app.models.trip import Trip
from app.services import (
    date_label_service,
    file_asset_service,
    id_service,
    itinerary_validation_service,
    mappers,
    markdown_service,
    plan_cover_service,
    planning_intake_service,
    trip_service,
)

logger = logging.getLogger("lvyousuotu")


def list_plans(session: Session, user_id: str) -> list[dto.Plan]:
    """List the user's plans, newest first."""
    plans = session.exec(
        select(PlanEntity)
        .where(PlanEntity.user_id == user_id)
        .order_by(PlanEntity.created_at.desc())
    ).all()
    return [mappers.plan_to_dto(p) for p in plans]


def _apply_derived_fields(entity: PlanEntity, data: ItineraryData) -> None:
    """Fill main-table fields derived from itinerary_data (deterministic)."""
    trip = data.trip_info
    entity.location = trip.destination
    entity.start_date = trip.start_date
    entity.end_date = trip.end_date
    entity.date_label = date_label_service.generate_label(trip.start_date, trip.end_date)
    entity.content = markdown_service.render_plan_content(data, entity.date_label)
    entity.itinerary_data = data.model_dump()


def save_plan(user_id: str, data: ItineraryData, trip_id: str | None = None) -> dto.Plan:
    """Create a new Plan (#7). Validates, derives fields, writes, then memory."""
    itinerary_validation_service.validate_itinerary(data)
    if data.planning_snapshot and not planning_intake_service.validated_snapshot_brief(data.planning_snapshot):
        data.planning_snapshot = None

    plan_id = id_service.new_plan_id()
    with session_scope() as session:
        trip_info = data.trip_info
        date_label = date_label_service.generate_label(trip_info.start_date, trip_info.end_date)
        trip = (
            trip_service.require_owned(session, user_id, trip_id)
            if trip_id
            else trip_service.create_in_session(
                session,
                user_id=user_id,
                location=trip_info.destination,
                start_date=trip_info.start_date,
                end_date=trip_info.end_date,
                date_label=date_label,
            )
        )
        entity = PlanEntity(
            id=plan_id,
            user_id=user_id,
            trip_id=trip.id,
            location="",
            date_label="",
            content="",
        )
        _apply_derived_fields(entity, data)
        session.add(entity)
        session.flush()
        trip_service.touch_from_artifact(
            trip,
            location=entity.location,
            start_date=entity.start_date,
            end_date=entity.end_date,
            date_label=entity.date_label,
            cover_image=None,
        )
        session.add(trip)
        needs_cover = not trip.cover_image
        saved_trip_id = trip.id
        result = mappers.plan_to_dto(entity)

    if needs_cover:
        _attach_plan_cover(user_id, saved_trip_id, plan_id, data)

    # The itinerary body is AI-produced, so it must never reinforce memory.
    # Users can explicitly confirm hard constraints in the travel-memory UI.
    return result


def _attach_plan_cover(
    user_id: str, trip_id: str, plan_id: str, data: ItineraryData,
) -> None:
    """Fill a blank trip cover. A failed image call must not undo the saved plan."""
    try:
        plan_cover_service.attach_cover(
            user_id=user_id, trip_id=trip_id, plan_id=plan_id, data=data,
        )
    except Exception:
        logger.exception("plan cover generation failed plan_id=%s", plan_id)


def update_plan(user_id: str, plan_id: str, data: ItineraryData) -> dto.Plan:
    """Overwrite an existing Plan (#8). 1004 if not found. Then memory."""
    itinerary_validation_service.validate_itinerary(data)

    with session_scope() as session:
        entity = session.exec(
            select(PlanEntity).where(
                PlanEntity.id == plan_id,
                PlanEntity.user_id == user_id,
            )
        ).first()
        if entity is None:
            raise NotFoundError("规划不存在或已被删除")
        previous = ItineraryData.model_validate(entity.itinerary_data)
        if data.model_dump(exclude={"planning_snapshot"}) == previous.model_dump(exclude={"planning_snapshot"}):
            data.planning_snapshot = previous.planning_snapshot
        else:
            data.planning_snapshot = None
        from app.models.base import utcnow

        _apply_derived_fields(entity, data)
        entity.updated_at = utcnow()
        session.add(entity)
        session.flush()
        result = mappers.plan_to_dto(entity)

    # Do not learn from AI-authored itinerary output (self-reinforcement loop).
    return result


def delete_plan(user_id: str, plan_id: str) -> None:
    """Delete a Plan (#11). Releases any plan_attachment references."""
    with session_scope() as session:
        entity = session.exec(
            select(PlanEntity).where(
                PlanEntity.id == plan_id,
                PlanEntity.user_id == user_id,
            )
        ).first()
        if entity is None:
            raise NotFoundError("规划不存在或已被删除")
        trip_id = entity.trip_id
        cover_paths = file_asset_service.list_reference_paths(
            session,
            user_id=user_id,
            owner_type="plan",
            owner_id=plan_id,
            role="plan_attachment",
        )
        trip = session.get(Trip, trip_id) if trip_id else None
        cover_image = trip.cover_image if trip is not None and trip.user_id == user_id else None
        file_asset_service.release_and_cleanup(
            session, owner_type="plan", owner_id=plan_id
        )
        session.delete(entity)
        session.flush()
        if trip_id and cover_image and cover_image in cover_paths:
            trip_service.refresh_cover(session, user_id, trip_id)


