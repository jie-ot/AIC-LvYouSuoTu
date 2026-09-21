"""Trip aggregate endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.core.dependencies import get_current_user_id
from app.core.responses import success
from app.db.session import get_session
from app.models import dto
from app.services import trip_service

router = APIRouter(tags=["trips"])


@router.get("/trips")
def list_trips(
    current_user_id: str = Depends(get_current_user_id),
    session: Session = Depends(get_session),
) -> dict:
    return success([
        item.model_dump(by_alias=True)
        for item in trip_service.list_trips(session, current_user_id)
    ])


@router.get("/trips/{trip_id}")
def get_trip(
    trip_id: str,
    current_user_id: str = Depends(get_current_user_id),
    session: Session = Depends(get_session),
) -> dict:
    return success(
        trip_service.get_trip(session, current_user_id, trip_id).model_dump(by_alias=True)
    )


@router.post("/trips")
def create_trip(
    payload: dto.TripCreateRequest,
    current_user_id: str = Depends(get_current_user_id),
    session: Session = Depends(get_session),
) -> dict:
    item = trip_service.create_trip(session, current_user_id, payload)
    session.commit()
    return success(item.model_dump(by_alias=True))


@router.patch("/trips/{trip_id}")
def update_trip(
    trip_id: str,
    payload: dto.TripUpdateRequest,
    current_user_id: str = Depends(get_current_user_id),
    session: Session = Depends(get_session),
) -> dict:
    item = trip_service.update_trip(session, current_user_id, trip_id, payload)
    session.commit()
    return success(item.model_dump(by_alias=True))


@router.delete("/trips/{trip_id}")
def delete_trip(
    trip_id: str,
    current_user_id: str = Depends(get_current_user_id),
    session: Session = Depends(get_session),
) -> dict:
    trip_service.delete_empty_trip(session, current_user_id, trip_id)
    session.commit()
    return success(None)
