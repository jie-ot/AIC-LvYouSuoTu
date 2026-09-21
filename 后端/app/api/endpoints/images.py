"""Image upload endpoint: #4 POST /images/upload (multipart/form-data)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, UploadFile

from app.core.dependencies import get_current_user_id
from app.core.responses import success
from app.services import image_service
from app.services.storage_service import MAX_UPLOAD_BYTES

router = APIRouter(tags=["images"])


def _read_upload_limited(file_obj, max_bytes: int = MAX_UPLOAD_BYTES) -> bytes:  # noqa: ANN001
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = file_obj.read(64 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            from app.core.exceptions import InvalidParamError

            raise InvalidParamError("文件超过大小上限")
        chunks.append(chunk)
    return b"".join(chunks)


@router.post("/images/upload")
def upload_image(
    file: UploadFile = File(...),
    current_user_id: str = Depends(get_current_user_id),
) -> dict:
    content = _read_upload_limited(file.file)
    result = image_service.save_uploaded_image(
        current_user_id, content, file.filename, file.content_type
    )
    return success(result.model_dump())
