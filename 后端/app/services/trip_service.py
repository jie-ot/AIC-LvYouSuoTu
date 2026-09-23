"""Trip aggregate queries and ownership-safe mutations."""

from __future__ import annotations

from collections import defaultdict

from sqlalchemy import update
from sqlmodel import Session, select

from app.core.exceptions import InvalidParamError, NotFoundError
from app.models import dto
from app.models.base import utcnow
from app.models.plan import Plan
from app.models.postcard import Postcard
from app.models.postcard_group import PostcardGroup
from app.models.report import Report
from app.models.trip import Trip
from app.models.user_memory import UserMemory
from app.models.user_memory_event import UserMemoryEvent
from app.services import file_asset_service, id_service, mappers


PLACEHOLDER_TITLE_PREFIXES = ("未命名", "旅行影像")
UNDATED_LABEL = "日期待定"


def default_title(location: str | None, date_label: str | None = None) -> str:
    value = (location or "").strip()
    date_text = (date_label or "").strip()
    has_date = bool(date_text) and date_text != UNDATED_LABEL
    if not value or value in {"未知目的地", "未知地点"}:
        return f"{date_text} 出发的一程" if has_date else "新的一程"
    return f"{value} · {date_text}" if has_date else value


def is_placeholder_title(title: str) -> bool:
    return title.startswith(PLACEHOLDER_TITLE_PREFIXES) or title == "新的一程"


def create_in_session(
    session: Session,
    *,
    user_id: str,
    title: str | None = None,
    location: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    date_label: str = "日期待定",
    cover_image: str | None = None,
) -> Trip:
    normalized_location = (location or "").strip()
    if normalized_location in {"未知目的地", "未知地点"}:
        normalized_location = ""
    trip = Trip(
        id=id_service.new_trip_id(),
        user_id=user_id,
        title=(title or default_title(normalized_location, date_label)).strip(),
        location=normalized_location or None,
        start_date=start_date,
        end_date=end_date,
        date_label=date_label or "日期待定",
        cover_image=cover_image,
    )
    session.add(trip)
    session.flush()
    return trip


def require_owned(session: Session, user_id: str, trip_id: str) -> Trip:
    trip = session.exec(
        select(Trip).where(Trip.id == trip_id, Trip.user_id == user_id)
    ).first()
    if trip is None:
        raise NotFoundError("旅行不存在或已被删除")
    return trip


def touch_from_artifact(
    trip: Trip,
    *,
    location: str | None,
    start_date: str | None,
    end_date: str | None,
    date_label: str,
    cover_image: str | None,
) -> None:
    normalized_location = (location or "").strip()
    if normalized_location in {"未知目的地", "未知地点"}:
        normalized_location = ""
    if not trip.location and normalized_location:
        trip.location = normalized_location
    if is_placeholder_title(trip.title) and trip.location not in {None, "未知目的地", "未知地点"}:
        trip.title = default_title(trip.location, date_label or trip.date_label)
    if not trip.start_date and start_date:
        trip.start_date = start_date
    if not trip.end_date and end_date:
        trip.end_date = end_date
    if trip.date_label == "日期待定" and date_label:
        trip.date_label = date_label
    if not trip.cover_image and cover_image:
        trip.cover_image = cover_image
    trip.updated_at = utcnow()


def refresh_cover(session: Session, user_id: str, trip_id: str | None) -> None:
    """Choose a remaining artifact cover after one of a trip's artifacts is removed."""
    if not trip_id:
        return
    trip = require_owned(session, user_id, trip_id)
    groups = session.exec(
        select(PostcardGroup).where(
            PostcardGroup.user_id == user_id,
            PostcardGroup.trip_id == trip_id,
        )
    ).all()
    reports = session.exec(
        select(Report).where(Report.user_id == user_id, Report.trip_id == trip_id)
    ).all()
    candidates = [
        (item.updated_at, item.cover_image)
        for item in [*groups, *reports]
        if item.cover_image
    ]
    if not candidates:
        plans = session.exec(
            select(Plan).where(Plan.user_id == user_id, Plan.trip_id == trip_id)
        ).all()
        for plan in plans:
            paths = file_asset_service.list_reference_paths(
                session,
                user_id=user_id,
                owner_type="plan",
                owner_id=plan.id,
                role="plan_attachment",
            )
            if paths:
                candidates.append((plan.updated_at, paths[-1]))
    trip.cover_image = max(candidates, default=(None, None), key=lambda item: item[0])[1]
    trip.updated_at = utcnow()
    session.add(trip)
    session.flush()


def _summary(
    trip: Trip,
    *,
    plan_count: int = 0,
    postcard_count: int = 0,
    report_count: int = 0,
) -> dto.TripSummary:
    return dto.TripSummary(
        id=trip.id,
        title=(default_title(trip.location, trip.date_label) if is_placeholder_title(trip.title) else trip.title),
        location=trip.location,
        start_date=trip.start_date,
        end_date=trip.end_date,
        date_label="" if trip.date_label == UNDATED_LABEL else trip.date_label,
        cover_image=trip.cover_image,
        plan_count=plan_count,
        postcard_count=postcard_count,
        report_count=report_count,
        updated_at=trip.updated_at.isoformat(),
    )


def list_trips(session: Session, user_id: str) -> list[dto.TripSummary]:
    trips = list(session.exec(
        select(Trip).where(Trip.user_id == user_id).order_by(Trip.updated_at.desc())
    ).all())
    trip_ids = {trip.id for trip in trips}
    if not trip_ids:
        return []
    plans = session.exec(select(Plan).where(Plan.user_id == user_id)).all()
    groups = session.exec(select(PostcardGroup).where(PostcardGroup.user_id == user_id)).all()
    reports = session.exec(select(Report).where(Report.user_id == user_id)).all()
    postcards = session.exec(select(Postcard).where(Postcard.user_id == user_id)).all()
    group_trip = {group.id: group.trip_id for group in groups}
    counts: dict[str, dict[str, int]] = defaultdict(lambda: {"plans": 0, "postcards": 0, "reports": 0})
    for plan in plans:
        if plan.trip_id in trip_ids:
            counts[str(plan.trip_id)]["plans"] += 1
    for report in reports:
        if report.trip_id in trip_ids:
            counts[str(report.trip_id)]["reports"] += 1
    for postcard in postcards:
        trip_id = group_trip.get(postcard.group_id)
        if trip_id in trip_ids:
            counts[str(trip_id)]["postcards"] += 1
    return [
        _summary(
            trip,
            plan_count=counts[trip.id]["plans"],
            postcard_count=counts[trip.id]["postcards"],
            report_count=counts[trip.id]["reports"],
        )
        for trip in trips
    ]


def get_trip(session: Session, user_id: str, trip_id: str) -> dto.TripDetail:
    trip = require_owned(session, user_id, trip_id)
    plans = list(session.exec(
        select(Plan).where(Plan.user_id == user_id, Plan.trip_id == trip_id).order_by(Plan.created_at.desc())
    ).all())
    groups = list(session.exec(
        select(PostcardGroup).where(
            PostcardGroup.user_id == user_id,
            PostcardGroup.trip_id == trip_id,
        ).order_by(PostcardGroup.created_at.desc())
    ).all())
    reports = list(session.exec(
        select(Report).where(Report.user_id == user_id, Report.trip_id == trip_id).order_by(Report.created_at.desc())
    ).all())
    group_dtos = []
    postcard_count = 0
    for group in groups:
        postcards = list(session.exec(
            select(Postcard).where(
                Postcard.user_id == user_id,
                Postcard.group_id == group.id,
            ).order_by(Postcard.sort_order.asc())
        ).all())
        postcard_count += len(postcards)
        group_dtos.append(mappers.postcard_group_to_dto(group, postcards))
    summary = _summary(
        trip,
        plan_count=len(plans),
        postcard_count=postcard_count,
        report_count=len(reports),
    )
    return dto.TripDetail(
        **summary.model_dump(),
        plans=[mappers.plan_to_dto(plan) for plan in plans],
        postcard_groups=group_dtos,
        reports=[
            mappers.report_to_dto(
                report,
                source_images=file_asset_service.list_reference_paths(
                    session,
                    user_id=user_id,
                    owner_type="report",
                    owner_id=report.id,
                    role="source_photo",
                ),
            )
            for report in reports
        ],
    )


def create_trip(session: Session, user_id: str, payload: dto.TripCreateRequest) -> dto.TripSummary:
    trip = create_in_session(
        session,
        user_id=user_id,
        title=payload.title,
        location=payload.location,
        start_date=payload.start_date,
        end_date=payload.end_date,
    )
    return _summary(trip)


def update_trip(
    session: Session,
    user_id: str,
    trip_id: str,
    payload: dto.TripUpdateRequest,
) -> dto.TripSummary:
    trip = require_owned(session, user_id, trip_id)
    trip.title = payload.title.strip()
    trip.updated_at = utcnow()
    session.add(trip)
    session.flush()
    detail = get_trip(session, user_id, trip_id)
    return dto.TripSummary.model_validate(detail.model_dump())


def delete_empty_trip(session: Session, user_id: str, trip_id: str) -> None:
    """Delete a trip container only after all of its content has been removed."""
    trip = require_owned(session, user_id, trip_id)
    has_content = any((
        session.exec(
            select(Plan.id).where(Plan.user_id == user_id, Plan.trip_id == trip_id)
        ).first(),
        session.exec(
            select(PostcardGroup.id).where(
                PostcardGroup.user_id == user_id,
                PostcardGroup.trip_id == trip_id,
            )
        ).first(),
        session.exec(
            select(Report.id).where(Report.user_id == user_id, Report.trip_id == trip_id)
        ).first(),
    ))
    if has_content:
        raise InvalidParamError("请先删除这次旅行中的行程、明信片和报告")
    # An empty container can still own a photo-observation snapshot. Withdraw
    # it and any confirmed pattern that cited it before removing the trip.
    if session.exec(select(UserMemory.id).where(UserMemory.user_id == user_id)).first() is not None:
        from app.services import memory_service

        memory_service.delete_trip_observation(
            session, user_id=user_id, trip_id=trip_id,
        )
    # Keep the event audit trail while detaching its foreign key from a trip
    # that no longer exists. The versioned event still records the trip ID in
    # its immutable delta where applicable.
    session.exec(update(UserMemoryEvent).where(
        UserMemoryEvent.user_id == user_id,
        UserMemoryEvent.trip_id == trip_id,
    ).values(trip_id=None))
    session.delete(trip)
    session.flush()
