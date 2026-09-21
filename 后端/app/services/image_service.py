"""Upload image service (#4): validate + persist + temporary FileAsset.

Combines `storage_service` (validation, UUID filename, disk write) with
`FileAssetService` (two-phase lifecycle, starts as `temporary`). The asset is
flipped to `attached` only later by `/api/generate` (《任务详细流程规范》五).
"""

from __future__ import annotations

import logging
import os

from sqlmodel import select

from app.core.exceptions import InternalError
from app.db.session import session_scope
from app.models import dto
from app.models.file_asset import FileAsset
from app.services import file_asset_service, storage_service

logger = logging.getLogger("lvyousuotu")


def save_uploaded_image(
    user_id: str,
    content: bytes,
    filename: str | None,
    content_type: str | None,
) -> dto.UploadResult:
    """Validate & store an uploaded image, returning {assetId, imageUrl}."""
    stored = storage_service.save_upload(content, filename, content_type)
    checksum = storage_service.calculate_file_sha256(stored.relative_path)
    try:
        with session_scope() as session:
            existing = session.exec(
                select(FileAsset).where(
                    FileAsset.user_id == user_id,
                    FileAsset.usage_type == "upload",
                    FileAsset.status.in_({"temporary", "attached"}),
                    FileAsset.checksum == checksum,
                )
            ).first()
            if existing is not None and os.path.isfile(
                storage_service.resolve_static_path(existing.relative_path)
            ):
                asset_id = existing.id
                image_url = existing.relative_path
                storage_service.delete_physical_file(stored.relative_path)
                return dto.UploadResult(asset_id=asset_id, image_url=image_url)
            # V3 introduced checksums, but migrated active uploads deliberately
            # keep NULL until first touch.  Backfill those rows before creating
            # a duplicate when a user uploads the same historical photo again.
            legacy_match: FileAsset | None = None
            legacy_assets = session.exec(
                select(FileAsset).where(
                    FileAsset.user_id == user_id,
                    FileAsset.usage_type == "upload",
                    FileAsset.status.in_({"temporary", "attached"}),
                    FileAsset.checksum.is_(None),
                )
            ).all()
            for legacy in legacy_assets:
                legacy_path = storage_service.resolve_static_path(
                    legacy.relative_path
                )
                if not os.path.isfile(legacy_path):
                    continue
                try:
                    legacy_checksum = storage_service.calculate_file_sha256(
                        legacy.relative_path
                    )
                except OSError:
                    logger.warning(
                        "legacy upload checksum backfill skipped asset=%s",
                        legacy.id,
                    )
                    continue
                legacy.checksum = legacy_checksum
                session.add(legacy)
                if legacy_match is None and legacy_checksum == checksum:
                    legacy_match = legacy
            if legacy_match is not None:
                asset_id = legacy_match.id
                image_url = legacy_match.relative_path
                storage_service.delete_physical_file(stored.relative_path)
                return dto.UploadResult(asset_id=asset_id, image_url=image_url)
            asset = file_asset_service.create_temporary(
                session,
                user_id=user_id,
                relative_path=stored.relative_path,
                mime_type=stored.mime_type,
                size_bytes=stored.size_bytes,
                usage_type="upload",
                checksum=checksum,
            )
            asset_id = asset.id
    except Exception as exc:  # noqa: BLE001
        # Physical file written but DB record failed → clean up the orphan.
        storage_service.delete_physical_file(stored.relative_path)
        raise InternalError("上传记录创建失败") from exc

    return dto.UploadResult(asset_id=asset_id, image_url=stored.relative_path)
