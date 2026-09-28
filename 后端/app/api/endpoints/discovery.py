"""Travel discovery API; every mutation is scoped to the injected user."""

from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from sqlmodel import Session

from app.core.dependencies import get_current_user_id
from app.core.responses import success
from app.db.session import get_session
from app.services.discovery import service
from app.services.discovery.schemas import AssistInput, FeedbackInput, PostInput, SearchInput

router = APIRouter(prefix="/discovery", tags=["discovery"])


@router.get("/feed")
def get_feed(
    background_tasks: BackgroundTasks,
    q: str = Query(default="", max_length=100),
    topic: str = Query(default="", max_length=20),
    mode: Literal["recommended", "saved", "mine", "hidden"] = "recommended",
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=50),
    use_semantic: bool = True,
    current_user_id: str = Depends(get_current_user_id),
    session: Session = Depends(get_session),
) -> dict:
    result = service.feed(session, current_user_id, query=q, topic=topic, mode=mode, offset=offset, limit=limit, use_semantic=use_semantic)
    if mode == "recommended" and use_semantic:
        from app.services.discovery.semantic_index import refresh_user_index
        background_tasks.add_task(refresh_user_index, current_user_id)
    return success(result)


@router.post("/searches")
def record_search(
    data: SearchInput, current_user_id: str = Depends(get_current_user_id),
    session: Session = Depends(get_session),
) -> dict:
    service.record_search(session, current_user_id, data.query)
    session.commit()
    return success(None)


@router.get("/share-options")
def get_share_options(
    trip_id: str = Query(min_length=1, max_length=80),
    current_user_id: str = Depends(get_current_user_id),
    session: Session = Depends(get_session),
) -> dict:
    return success(service.share_options(session, current_user_id, trip_id))


@router.post("/assist")
def assist(data: AssistInput, current_user_id: str = Depends(get_current_user_id)) -> dict:
    return success(service.assist(data))


@router.post("/posts")
def publish(
    data: PostInput, current_user_id: str = Depends(get_current_user_id),
    session: Session = Depends(get_session),
) -> dict:
    result = service.publish(session, current_user_id, data)
    session.commit()
    return success(result)


@router.get("/posts/{post_id}")
def get_post(
    post_id: str, current_user_id: str = Depends(get_current_user_id),
    session: Session = Depends(get_session),
) -> dict:
    return success(service.detail(session, current_user_id, post_id))


@router.put("/posts/{post_id}/feedback")
def feedback(
    post_id: str, data: FeedbackInput, current_user_id: str = Depends(get_current_user_id),
    session: Session = Depends(get_session),
) -> dict:
    result = service.set_feedback(session, current_user_id, post_id, data.action)
    session.commit()
    return success(result)


@router.delete("/posts/{post_id}")
def withdraw(
    post_id: str, current_user_id: str = Depends(get_current_user_id),
    session: Session = Depends(get_session),
) -> dict:
    service.withdraw(session, current_user_id, post_id)
    session.commit()
    return success(None)
