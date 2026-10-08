"""AI generation endpoint: #5 POST /generate."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.core import generation_progress

from app.core.business_logging import business_task
from app.core.dependencies import get_current_user_id
from app.core.responses import success
from app.models.dto import GenerateRequest
from app.services import generation_service

router = APIRouter(tags=["generate"])


@router.post("/generate")
def generate(
    payload: GenerateRequest,
    current_user_id: str = Depends(get_current_user_id),
) -> dict:
    with generation_progress.track(
        current_user_id, payload.client_request_id, photos=len(payload.photos),
        cards=(payload.options.postcard_count or 3) if payload.options.generate_postcards else 0,
        report=payload.options.generate_report,
    ), business_task(
        "generate",
        user_id=current_user_id,
        photo_count=len(payload.photos),
        generate_postcards=payload.options.generate_postcards,
        generate_report=payload.options.generate_report,
    ):
        result = generation_service.generate(current_user_id, payload)
    return success(result.model_dump(by_alias=True))


@router.get("/generate/progress")
def read_generation_progress(
    request_id: str = Query(..., min_length=8, max_length=64),
    current_user_id: str = Depends(get_current_user_id),
) -> dict:
    return success(generation_progress.snapshot(current_user_id, request_id))
