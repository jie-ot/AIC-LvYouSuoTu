"""User-facing travel-memory endpoints with optimistic concurrency."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session

from app.core.dependencies import get_current_user_id
from app.core.exceptions import InvalidParamError
from app.core.responses import success
from app.db.session import get_session
from app.models.dto import (
    MemoryDescriptionUpdateRequest,
    MemoryItemCreateRequest,
    MemoryItemPatchRequest,
    MemoryOverviewUpdateRequest,
    MemoryPatternConfirmRequest,
    MemoryPlanningPreferencesUpdateRequest,
    MemorySettingsUpdateRequest,
)
from app.services import memory_insight_service, memory_service
from app.services.memory_display_adapter import MemoryDisplayAdapter

router = APIRouter(tags=["memories"])
adapter = MemoryDisplayAdapter()


def _response(memory, session: Session, user_id: str) -> dict:  # noqa: ANN001
    return success(adapter.to_display(
        memory, session=session, user_id=user_id,
    ).model_dump(by_alias=True))


@router.get("/memories/travel")
def get_travel_memory(
    current_user_id: str = Depends(get_current_user_id),
    session: Session = Depends(get_session),
) -> dict:
    memory = memory_service.get_or_create_current_memory(session, current_user_id)
    session.commit()
    return _response(memory, session, current_user_id)


@router.post("/memories/travel/items")
def create_travel_memory_item(
    payload: MemoryItemCreateRequest,
    current_user_id: str = Depends(get_current_user_id),
    session: Session = Depends(get_session),
) -> dict:
    memory = memory_service.add_memory_item(
        session,
        user_id=current_user_id,
        text=payload.text,
        category=payload.category,
        expected_version=payload.expected_version,
    )
    session.commit()
    return _response(memory, session, current_user_id)


@router.patch("/memories/travel/items/{item_id}")
def patch_travel_memory_item(
    item_id: str,
    payload: MemoryItemPatchRequest,
    current_user_id: str = Depends(get_current_user_id),
    session: Session = Depends(get_session),
) -> dict:
    memory = memory_service.patch_memory_item(
        session,
        user_id=current_user_id,
        item_id=item_id,
        text=payload.text,
        category=payload.category,
        enabled=payload.enabled,
        confirm=payload.confirm,
        expected_version=payload.expected_version,
    )
    session.commit()
    return _response(memory, session, current_user_id)


@router.delete("/memories/travel/items/{item_id}")
def delete_travel_memory_item(
    item_id: str,
    expected_version: int | None = Query(default=None, alias="expectedVersion", ge=1),
    current_user_id: str = Depends(get_current_user_id),
    session: Session = Depends(get_session),
) -> dict:
    memory = memory_service.delete_memory_item(
        session,
        user_id=current_user_id,
        item_id=item_id,
        expected_version=expected_version,
    )
    session.commit()
    return _response(memory, session, current_user_id)


@router.patch("/memories/travel/settings")
def update_travel_memory_settings(
    payload: MemorySettingsUpdateRequest,
    current_user_id: str = Depends(get_current_user_id),
    session: Session = Depends(get_session),
) -> dict:
    memory = memory_service.set_memory_enabled(
        session,
        user_id=current_user_id,
        enabled=payload.enabled,
        expected_version=payload.expected_version,
    )
    session.commit()
    return _response(memory, session, current_user_id)


@router.post("/memories/travel/patterns/{pattern_id}/confirm")
def confirm_travel_memory_pattern(
    pattern_id: str,
    payload: MemoryPatternConfirmRequest,
    current_user_id: str = Depends(get_current_user_id),
    session: Session = Depends(get_session),
) -> dict:
    memory = memory_service.get_or_create_current_memory(session, current_user_id)
    _stats, _footprints, patterns = memory_insight_service.build_context(
        session, current_user_id, memory.memory_json,
    )
    pattern = next((item for item in patterns if item.id == pattern_id), None)
    if pattern is None:
        raise InvalidParamError("这条观察已变化，请刷新后重试")
    memory = memory_service.confirm_observed_pattern(
        session,
        user_id=current_user_id,
        pattern=pattern,
        expected_version=payload.expected_version,
    )
    session.commit()
    return _response(memory, session, current_user_id)


@router.put("/memories/travel/descriptions/{description_id}")
def update_travel_memory_description(
    description_id: str,
    payload: MemoryDescriptionUpdateRequest,
    current_user_id: str = Depends(get_current_user_id),
    session: Session = Depends(get_session),
) -> dict:
    if not payload.title.strip() or not payload.content.strip():
        raise InvalidParamError("记忆内容不能为空")
    memory = memory_service.update_preference(
        session, user_id=current_user_id, preference_id=description_id,
        title=payload.title, content=payload.content,
        expected_version=payload.expected_version,
    )
    session.commit()
    return _response(memory, session, current_user_id)


@router.put("/memories/travel/overview")
def update_travel_memory_overview(
    payload: MemoryOverviewUpdateRequest,
    current_user_id: str = Depends(get_current_user_id),
    session: Session = Depends(get_session),
) -> dict:
    if not payload.title.strip() or not payload.content.strip():
        raise InvalidParamError("概述内容不能为空")
    memory = memory_service.update_manual_fields(
        session, user_id=current_user_id, key="display_overview",
        value={"title": payload.title.strip(), "content": payload.content.strip()},
        expected_version=payload.expected_version,
    )
    session.commit()
    return _response(memory, session, current_user_id)


@router.put("/memories/travel/planning-preferences")
def update_travel_memory_planning_preferences(
    payload: MemoryPlanningPreferencesUpdateRequest,
    current_user_id: str = Depends(get_current_user_id),
    session: Session = Depends(get_session),
) -> dict:
    values = {
        key: str(getattr(payload, key)).strip()
        for key in ("transport", "hotel", "attractions", "food", "pace", "other")
    }
    memory = memory_service.update_manual_fields(
        session, user_id=current_user_id, key="planning_preferences", value=values,
        expected_version=payload.expected_version,
    )
    session.commit()
    return _response(memory, session, current_user_id)


@router.delete("/memories/travel/descriptions/{description_id}")
def delete_travel_memory_description(
    description_id: str,
    expected_version: int | None = Query(default=None, alias="expectedVersion", ge=1),
    current_user_id: str = Depends(get_current_user_id),
    session: Session = Depends(get_session),
) -> dict:
    memory = memory_service.forget_preference(
        session, user_id=current_user_id, preference_id=description_id,
        expected_version=expected_version,
    )
    session.commit()
    return _response(memory, session, current_user_id)
