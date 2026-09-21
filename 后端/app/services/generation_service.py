"""Evidence-bounded postcard/report/memory generation flow (V3)."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from threading import Lock

from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.ai import orchestrator
from app.ai.schemas import (
    MemoryUpdateResult,
    PhotoAnalysisResult,
    PostcardPlanItem,
    PostcardPlanResult,
    PostcardSelectionItem,
    PostcardSelectionResult,
    ReportDraftResult,
)
from app.core.business_logging import call_in_current_context, log_event, timed_stage
from app.core.config import settings
from app.core.exceptions import AIGenerationError, BusinessError, InternalError, InvalidParamError
from app.db.session import session_scope
from app.models import dto
from app.models.file_asset import FileAsset
from app.models.generation_operation import GenerationOperation
from app.models.postcard import Postcard as PostcardEntity
from app.models.postcard_group import PostcardGroup as PostcardGroupEntity
from app.models.report import Report as ReportEntity
from app.models.trip import Trip as TripEntity
from app.models.base import utcnow
from app.services import (
    date_label_service,
    file_asset_service,
    id_service,
    mappers,
    memory_service,
    postcard_renderer,
    profile_engine,
    storage_service,
    trip_service,
)
from app.services.storage_service import ALLOWED_MIME_TYPES, MAX_UPLOAD_BYTES, PREFIX_UPLOADS

logger = logging.getLogger("lvyousuotu")
MAX_PHOTO_COUNT = 50
MAX_TOTAL_PHOTO_BYTES = 200 * 1024 * 1024
MAX_POSTCARD_COUNT = 5
POSTCARD_EXCLUDED_SCENES_MESSAGE = (
    "所有可用照片都包含你明确要求避开的场景，请调整要求或更换照片"
)


@dataclass(frozen=True)
class PostcardRender:
    title: str
    relative_path: str
    sort_order: int
    asset_id: str
    source_asset_ids: list[str]
    render_mode: str


def _warning(
    code: str, message: str, feature: str, *, item_index: int | None = None,
    retryable: bool = False,
) -> dto.GenerationWarning:
    return dto.GenerationWarning(
        code=code, message=message, feature=feature,
        item_index=item_index, retryable=retryable,
    )


def _request_hash(request: dto.GenerateRequest) -> str:
    payload = request.model_dump(mode="json", by_alias=True, exclude={"client_request_id"})
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _begin_operation(
    user_id: str, request: dto.GenerateRequest,
) -> tuple[str, dto.GenerateResult | None, dict | None]:
    request_hash = _request_hash(request)
    client_request_id = request.client_request_id or f"legacy-{uuid.uuid4().hex}"
    try:
        with session_scope() as session:
            existing = session.exec(
                select(GenerationOperation).where(
                    GenerationOperation.user_id == user_id,
                    GenerationOperation.client_request_id == client_request_id,
                )
            ).first()
            if existing is not None:
                if existing.request_hash != request_hash:
                    raise InvalidParamError("这次生成请求已失效，请重新提交")
                if existing.status in {"completed", "partial"} and existing.response_json:
                    return (
                        existing.id,
                        dto.GenerateResult.model_validate(existing.response_json),
                        dict(existing.pending_memory_payload) if existing.pending_memory_payload else None,
                    )
                if existing.status == "processing":
                    raise InvalidParamError("相同生成请求正在处理，请勿重复提交")
                if existing.status == "failed":
                    retry = session.exec(
                        update(GenerationOperation)
                        .where(
                            GenerationOperation.id == existing.id,
                            GenerationOperation.status == "failed",
                        )
                        .values(
                            status="processing",
                            postcard_status="skipped",
                            report_status="skipped",
                            memory_status="skipped",
                            response_json=None,
                            pending_memory_payload=None,
                            error_message=None,
                            updated_at=utcnow(),
                        )
                    )
                    if retry.rowcount != 1:
                        raise InvalidParamError("相同生成请求正在处理，请勿重复提交")
                    return existing.id, None, None
                raise InvalidParamError("生成请求状态异常，请刷新后重试")
            operation = GenerationOperation(
                id=id_service.new_generation_operation_id(), user_id=user_id,
                client_request_id=client_request_id, request_hash=request_hash,
                status="processing",
            )
            session.add(operation)
            session.flush()
            operation_id = operation.id
        return operation_id, None, None
    except IntegrityError as exc:
        raise InvalidParamError("相同生成请求已被接收，请勿重复提交") from exc


def _mark_operation_failed(operation_id: str, message: str) -> None:
    try:
        with session_scope() as session:
            operation = session.get(GenerationOperation, operation_id)
            if operation is not None:
                operation.status = "failed"
                operation.error_message = message[:300]
                operation.updated_at = utcnow()
                session.add(operation)
    except Exception:  # noqa: BLE001
        logger.exception("failed to mark generation operation", extra={"operation_id": operation_id})


def _validate_and_load_photos(
    session: Session, user_id: str, photos: list[dto.UploadedPhoto]
) -> list[FileAsset]:
    if not 1 <= len(photos) <= MAX_PHOTO_COUNT:
        raise InvalidParamError("照片数量必须为 1–50 张")
    asset_ids = [photo.asset_id for photo in photos]
    if len(asset_ids) != len(set(asset_ids)):
        raise InvalidParamError("不能重复提交同一张照片")
    total_bytes = 0
    assets: list[FileAsset] = []
    seen_checksums: set[str] = set()
    for photo in photos:
        if not photo.image_url.startswith(PREFIX_UPLOADS) or ".." in photo.image_url:
            raise InvalidParamError("所选照片已失效，请重新选择")
        asset = session.get(FileAsset, photo.asset_id)
        if asset is None or asset.user_id != user_id:
            raise InvalidParamError("所选照片不存在，请重新选择")
        if asset.relative_path != photo.image_url:
            raise InvalidParamError("照片信息已变化，请重新选择")
        if asset.status not in {"temporary", "attached"} or asset.usage_type != "upload":
            raise InvalidParamError("所选照片当前无法使用，请重新选择")
        if asset.mime_type not in ALLOWED_MIME_TYPES or not 0 < asset.size_bytes <= MAX_UPLOAD_BYTES:
            raise InvalidParamError("照片格式或大小不符合要求")
        if not os.path.isfile(storage_service.resolve_static_path(asset.relative_path)):
            raise InvalidParamError("照片文件已不存在")
        checksum = storage_service.calculate_file_sha256(asset.relative_path)
        if checksum in seen_checksums:
            raise InvalidParamError("不能重复提交内容相同的照片")
        seen_checksums.add(checksum)
        if asset.checksum != checksum:
            asset.checksum = checksum
            session.add(asset)
        total_bytes += asset.size_bytes
        assets.append(asset)
    if total_bytes > MAX_TOTAL_PHOTO_BYTES:
        raise InvalidParamError("本次照片总大小超过上限")
    return assets


def _validate_analysis(analysis: PhotoAnalysisResult, source_ids: set[str]) -> None:
    if (
        not analysis.photos
        or len(analysis.photos) != len(source_ids)
        or {item.asset_id for item in analysis.photos} != source_ids
    ):
        raise AIGenerationError("AI 照片分析结果不完整")


def _parse_legacy_postcard_count(requirements: str) -> int | None:
    values = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5}
    patterns = (
        r"([1-5一二两三四五])\s*张\s*明信片",
        r"明信片[^\n，。,]{0,8}?([1-5一二两三四五])\s*张",
    )
    found: set[int] = set()
    for pattern in patterns:
        for token in re.findall(pattern, requirements):
            found.add(int(token) if token.isdigit() else values[token])
    return next(iter(found)) if len(found) == 1 else None


def _requested_postcard_count(options: dto.GenerateOptions, requirements: str) -> int:
    return options.postcard_count or _parse_legacy_postcard_count(requirements) or 3


def _deterministic_selection(
    analysis: PhotoAnalysisResult, requested: int, requirements: str = "",
) -> tuple[PostcardSelectionResult, bool]:
    useful = [photo for photo in analysis.photos if photo.suitability != "unsuitable"]
    if not useful:
        raise AIGenerationError("这组照片暂时不适合生成作品，请更换清晰且与旅行相关的照片")
    useful.sort(key=lambda photo: (photo.suitability != "good", -photo.analysis_confidence, photo.asset_id))
    selected = []
    used_tags: set[str] = set()
    preference_scores = _scene_preference_scores(requirements)
    excluded_tags = {tag for tag, score in preference_scores.items() if score < 0}
    candidates = [
        photo
        for photo in useful
        if not excluded_tags.intersection(photo.scene_tags)
    ]
    if not candidates:
        raise AIGenerationError(POSTCARD_EXCLUDED_SCENES_MESSAGE)
    while candidates and len(selected) < requested:
        best = min(
            candidates,
            key=lambda photo: (
                photo.suitability != "good",
                -sum(max(0, preference_scores.get(tag, 0)) for tag in photo.scene_tags),
                -len(set(photo.scene_tags) - used_tags),
                -photo.analysis_confidence,
                photo.asset_id,
            ),
        )
        selected.append(best)
        used_tags.update(best.scene_tags)
        candidates.remove(best)
    return (
        PostcardSelectionResult(items=[PostcardSelectionItem(source_asset_ids=[photo.asset_id]) for photo in selected]),
        len(selected) < requested,
    )


def _scene_preference_scores(requirements: str) -> dict[str, int]:
    """Parse only explicit scene wishes; never rewrite observed photo facts."""
    concepts = {
        "coast": ("海边", "海岸", "滨水"),
        "mountain": ("山野", "山景", "山区"),
        "nature": ("自然", "森林", "湖畔", "风景"),
        "city": ("城市", "都市", "建筑"),
        "street": ("街区", "街道", "老街"),
        "culture": ("人文", "文化", "历史", "博物馆", "古城"),
        "food": ("美食", "小吃", "餐饮", "咖啡"),
        "night": ("夜景", "夜间", "霓虹"),
    }
    scores: dict[str, int] = {}
    for tag, words in concepts.items():
        score = 0
        for word in words:
            polarity = memory_service.preference_term_polarity(requirements, word)
            score += 2 * polarity
        if score:
            scores[tag] = score
    return scores


def generate(user_id: str, request: dto.GenerateRequest) -> dto.GenerateResult:
    options = request.options
    if not options.generate_postcards and not options.generate_report:
        raise InvalidParamError("请至少选择生成明信片或报告其一")
    operation_id, replay, replay_pending = _begin_operation(user_id, request)
    if replay is not None:
        if replay_pending and replay.memory_status in {"pending", "failed"}:
            replay.warnings = [warning for warning in replay.warnings if warning.feature != "memory"]
            replay.memory_status = _retry_pending_memory(
                user_id, operation_id, request, replay_pending, replay.warnings,
            )
            replay.status = "completed" if replay.memory_status == "success" and replay.postcard_status != "failed" and replay.report_status != "failed" else "partial"
            _finalize_operation(operation_id, replay)
        return replay

    source_asset_ids = [photo.asset_id for photo in request.photos]
    generated_temp_asset_ids: list[str] = []
    warnings: list[dto.GenerationWarning] = []
    warnings_lock = Lock()
    try:
        with session_scope() as session:
            validated_assets = _validate_and_load_photos(session, user_id, request.photos)
            source_path_by_asset = {
                asset.id: asset.relative_path for asset in validated_assets
            }
            source_checksum_by_asset = {
                asset.id: str(asset.checksum) for asset in validated_assets
            }

        photo_metas = [
            {
                "asset_id": p.asset_id,
                "image_url": source_path_by_asset[p.asset_id],
                "taken_at": p.taken_at,
                "location": p.location,
            }
            for p in request.photos
        ]
        image_data_urls = _read_image_data_urls([source_path_by_asset[p.asset_id] for p in request.photos])
        data_url_by_asset = dict(zip(source_asset_ids, image_data_urls, strict=True))
        with timed_stage("generate_photo_analysis", photo_count=len(photo_metas)):
            analysis = orchestrator.analyze_photos(
                photo_metas=photo_metas, image_data_urls=image_data_urls,
                requirements=request.requirements, memory_summary="",
            )
        _validate_analysis(analysis, set(source_asset_ids))
        if all(photo.suitability == "unsuitable" for photo in analysis.photos):
            raise AIGenerationError("这组照片暂时不适合生成作品，请更换清晰且与旅行相关的照片")
        log_event(
            "generate_photo_analysis_result", status="success",
            photo_count=len(analysis.photos),
            suitability_counts={level: sum(p.suitability == level for p in analysis.photos) for level in ("good", "usable", "unsuitable")},
            result_hash=hashlib.sha256(analysis.model_dump_json().encode()).hexdigest()[:16],
        )

        location = (analysis.overall_location or "未知目的地").strip() or "未知目的地"
        date_label = date_label_service.generate_label(analysis.start_date, analysis.end_date)
        postcard_renders: list[PostcardRender] = []
        report_draft: ReportDraftResult | None = None
        postcard_status = "skipped"
        report_status = "skipped"
        memory_status = "pending" if options.learn_preferences else "skipped"
        memory_update: MemoryUpdateResult | None = None
        memory_proposal_failed = False
        postcard_user_error: str | None = None

        with ThreadPoolExecutor(max_workers=3) as executor:
            postcard_future: Future[list[PostcardRender]] | None = None
            report_future: Future[ReportDraftResult] | None = None
            memory_future: Future[MemoryUpdateResult] | None = None
            if options.generate_postcards:
                postcard_future = executor.submit(call_in_current_context(
                    _generate_postcards, user_id=user_id, analysis=analysis,
                    requirements=request.requirements,
                    requested_count=_requested_postcard_count(options, request.requirements),
                    data_url_by_asset=data_url_by_asset,
                    generated_temp_asset_ids=generated_temp_asset_ids,
                    warnings=warnings, warnings_lock=warnings_lock,
                ))
            if options.generate_report:
                report_future = executor.submit(call_in_current_context(
                    _draft_report_v3, analysis=analysis, requirements=request.requirements,
                    image_url_by_asset=source_path_by_asset,
                    warnings=warnings, warnings_lock=warnings_lock,
                ))
            if options.learn_preferences:
                memory_future = executor.submit(call_in_current_context(
                    _propose_memory_update, location=location, analysis=analysis,
                    requirements=(
                        request.memory_requirements
                        if request.memory_requirements is not None
                        else request.requirements
                    ),
                ))

            if postcard_future is not None:
                try:
                    postcard_renders = postcard_future.result()
                    postcard_status = "success"
                except Exception as exc:  # noqa: BLE001
                    postcard_status = "failed"
                    if (
                        isinstance(exc, AIGenerationError)
                        and exc.message == POSTCARD_EXCLUDED_SCENES_MESSAGE
                    ):
                        postcard_user_error = exc.message
                        warnings.append(_warning(
                            "POSTCARD_SCENES_EXCLUDED",
                            exc.message,
                            "postcard",
                        ))
                    else:
                        warnings.append(_warning(
                            "POSTCARD_BRANCH_FAILED",
                            "明信片生成失败，其他作品不受影响",
                            "postcard",
                            retryable=True,
                        ))
                    logger.warning("postcard branch failed: %s", type(exc).__name__)
            if report_future is not None:
                try:
                    report_draft = report_future.result()
                    report_status = "success"
                except Exception as exc:  # noqa: BLE001
                    report_status = "failed"
                    warnings.append(_warning("REPORT_BRANCH_FAILED", "旅行报告生成失败，其他内容不受影响", "report", retryable=True))
                    logger.warning("report branch failed: %s", type(exc).__name__)
            if memory_future is not None:
                try:
                    memory_update = memory_future.result()
                except Exception as exc:  # noqa: BLE001
                    memory_status = "failed"
                    memory_proposal_failed = True
                    warnings.append(_warning("MEMORY_PROPOSAL_FAILED", "内容已生成，但填写的要求未加入旅行记忆", "memory", retryable=True))
                    logger.warning("memory proposal failed: %s", type(exc).__name__)

        if postcard_status != "success" and report_status != "success":
            if postcard_user_error and report_status == "skipped":
                raise AIGenerationError(postcard_user_error)
            raise AIGenerationError("所选作品均未生成，请稍后重试")
        useful_source_asset_ids = [
            photo.asset_id for photo in analysis.photos if photo.suitability != "unsuitable"
        ]
        report_cover_source_id = _representative_asset_id(analysis)
        pending = None
        if memory_update is not None:
            pending = {
                "stage": "merge",
                "add_preferences": memory_update.add_preferences,
                "confidence": memory_update.confidence,
                "trip_fingerprint": _trip_fingerprint(
                    analysis, source_checksum_by_asset,
                ),
            }
        elif memory_proposal_failed:
            # Keep no prompt, photo semantics or model output in the operation.
            # The same authenticated request can replay just analysis → proposal
            # → merge while preserving the already-saved postcard/report.
            pending = {"stage": "proposal"}
        result = _persist_results(
            user_id=user_id, operation_id=operation_id, options=options,
            requested_trip_id=request.trip_id,
            location=location, date_label=date_label, start_date=analysis.start_date,
            end_date=analysis.end_date, source_asset_ids=useful_source_asset_ids,
            postcard_renders=postcard_renders, report_draft=report_draft,
            report_cover_source_id=report_cover_source_id,
            postcard_status=postcard_status, report_status=report_status,
            memory_status=memory_status, warnings=warnings, pending_memory_payload=pending,
            analysis=analysis, uploaded_photos=request.photos,
        )

        if pending is not None and pending.get("stage") != "proposal":
            memory_status = _merge_pending_memory(user_id, operation_id, pending, warnings)
            result.memory_status = memory_status
            if memory_status == "failed":
                result.status = "partial"
        _finalize_operation(operation_id, result)
        return result
    except BusinessError as exc:
        _discard(generated_temp_asset_ids)
        _mark_operation_failed(operation_id, exc.message)
        raise
    except Exception as exc:  # noqa: BLE001
        _discard(generated_temp_asset_ids)
        _mark_operation_failed(operation_id, type(exc).__name__)
        raise InternalError("生成过程发生内部错误") from exc


def _read_image_data_urls(image_urls: list[str]) -> list[str]:
    workers = max(1, min(len(image_urls), settings.GENERATION_FILE_IO_PARALLELISM))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        return list(executor.map(storage_service.read_file_as_base64_data_url, image_urls))


def _generate_postcards(
    *, user_id: str, analysis: PhotoAnalysisResult, requirements: str,
    requested_count: int, data_url_by_asset: dict[str, str],
    generated_temp_asset_ids: list[str], warnings: list[dto.GenerationWarning],
    warnings_lock: Lock,
) -> list[PostcardRender]:
    selection, reduced = _deterministic_selection(
        analysis, requested_count, requirements,
    )
    if reduced:
        warnings.append(_warning(
            "COUNT_REDUCED",
            f"符合质量与场景要求的照片仅有 {len(selection.items)} 张，明信片数量已自动减少",
            "postcard",
        ))
    selected_ids = [item.source_asset_ids[0] for item in selection.items]
    try:
        plan = orchestrator.create_postcard_creative_plan(
            analysis=analysis, selection=selection, selected_asset_ids=selected_ids,
            image_data_urls=[data_url_by_asset[asset_id] for asset_id in selected_ids],
            requirements=requirements, memory_summary="",
        )
        plan_items = _enforce_postcard_plan(plan, selection)
    except Exception as exc:  # noqa: BLE001
        logger.warning("postcard creative fallback: %s", type(exc).__name__)
        plan_items = _fallback_postcard_plan(analysis, selection)
        warnings.append(_warning(
            "CREATIVE_FALLBACK", "创意排版暂未完成，已使用简洁模板", "postcard", retryable=True,
        ))

    workers = max(1, min(len(plan_items), settings.GENERATION_IMAGE_PARALLELISM))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [
            executor.submit(call_in_current_context(
                _render_and_store_postcard, user_id=user_id, index=index, item=item,
                source_data_url=data_url_by_asset[item.source_asset_ids[0]],
                generated_temp_asset_ids=generated_temp_asset_ids,
                warnings=warnings, warnings_lock=warnings_lock,
            ))
            for index, item in enumerate(plan_items)
        ]
        renders: list[PostcardRender] = []
        for index, future in enumerate(futures):
            try:
                renders.append(future.result())
            except Exception as exc:  # noqa: BLE001
                warnings.append(_warning(
                    "POSTCARD_ITEM_FAILED", "这张明信片未能生成，其他明信片已保留",
                    "postcard", item_index=index, retryable=True,
                ))
                logger.warning("postcard item failed index=%d reason=%s", index, type(exc).__name__)
        if not renders:
            raise AIGenerationError("所有明信片均生成失败")
        if len(renders) < len(plan_items):
            warnings.append(_warning(
                "POSTCARD_COUNT_REDUCED", f"已成功保留 {len(renders)} 张明信片，失败卡片未影响其他结果", "postcard",
            ))
        return sorted(renders, key=lambda item: item.sort_order)


def _enforce_postcard_plan(
    plan: PostcardPlanResult, selection: PostcardSelectionResult,
) -> list[PostcardPlanItem]:
    if len(plan.items) != len(selection.items):
        raise AIGenerationError("明信片创意数量不一致")
    for item, selected in zip(plan.items, selection.items, strict=True):
        if item.source_asset_ids != selected.source_asset_ids or not 2 <= len(item.title.strip()) <= 12:
            raise AIGenerationError("明信片创意未严格对应后端选图")
    return list(plan.items)


def _fallback_postcard_plan(
    analysis: PhotoAnalysisResult, selection: PostcardSelectionResult,
) -> list[PostcardPlanItem]:
    by_id = {photo.asset_id: photo for photo in analysis.photos}
    items: list[PostcardPlanItem] = []
    for selected in selection.items:
        photo = by_id[selected.source_asset_ids[0]]
        title = _fallback_title(photo.scene_tags)
        items.append(PostcardPlanItem(
            design_concept="保留原图的场景与光线，只做克制的明信片整理",
            photo_transformation="不改变主体和事实内容，仅进行轻微色彩平衡与安全留白",
            visual_device="以原图中已有的光线和空间层次作为视觉重心",
            typography="由本地排版在安全区内添加小尺寸标题，无可用字体时保持无字",
            title=title, source_asset_ids=list(selected.source_asset_ids), extra_texts=[],
            image_prompt="明信片设计：保留原图主体、构图和地点线索，只做轻微自然调色与光线整理，不添加文字、邮戳、日期、人物或虚构地标。",
        ))
    return items


def _fallback_title(tags: list[str]) -> str:
    for key, title in (("mountain", "山景"), ("coast", "海岸"), ("culture", "人文景观"), ("city", "城市"), ("night", "夜景"), ("street", "街区")):
        if key in tags:
            return title
    return "旅行明信片"


def _render_and_store_postcard(
    *, user_id: str, index: int, item: PostcardPlanItem, source_data_url: str,
    generated_temp_asset_ids: list[str], warnings: list[dto.GenerationWarning],
    warnings_lock: Lock,
) -> PostcardRender:
    fallback = False
    relative_path = storage_service.build_postcard_relative_path("jpg")
    try:
        image_result = orchestrator.render_postcard_image(
            prompt=item.image_prompt, image_data_urls=[source_data_url],
            design_concept=item.design_concept, photo_transformation=item.photo_transformation,
            visual_device=item.visual_device, typography=item.typography,
            title="", extra_texts=[],
        )
        if not image_result.image_url:
            raise InternalError("图片生成服务暂未返回结果")
        downloaded = storage_service.download_to_static(image_result.image_url, relative_path)
        with open(downloaded.abs_path, "rb") as file:
            source = file.read()
    except Exception as exc:  # noqa: BLE001
        fallback = True
        source = postcard_renderer.decode_data_url(source_data_url)
        with warnings_lock:
            warnings.append(_warning(
                "POSTCARD_LOCAL_FALLBACK", "图片处理未完成，该张已使用原图简洁模板",
                "postcard", item_index=index, retryable=True,
            ))
        logger.warning("postcard item fallback index=%d reason=%s", index, type(exc).__name__)
    try:
        composed = postcard_renderer.compose_postcard(source, item.title, fallback=fallback)
        stored = storage_service.save_bytes_to_static(composed.content, relative_path, "image/jpeg")
    except Exception:
        storage_service.delete_physical_file(relative_path)
        raise
    if composed.font_missing:
        with warnings_lock:
            warnings.append(_warning(
                "FONT_MISSING", "未找到可用的中文字体，该张已使用无字模板，标题仍会在卡片下方显示",
                "postcard", item_index=index,
            ))
    try:
        with session_scope() as session:
            asset = file_asset_service.create_temporary(
                session, user_id=user_id, relative_path=stored.relative_path,
                mime_type=stored.mime_type, size_bytes=stored.size_bytes,
                usage_type="generated_postcard",
            )
            asset_id = asset.id
    except Exception:
        storage_service.delete_physical_file(stored.relative_path)
        raise
    with warnings_lock:
        generated_temp_asset_ids.append(asset_id)
    return PostcardRender(
        title=item.title, relative_path=stored.relative_path, sort_order=index,
        asset_id=asset_id, source_asset_ids=list(item.source_asset_ids),
        render_mode=composed.render_mode,
    )


def _draft_report_v3(
    *, analysis: PhotoAnalysisResult, requirements: str,
    image_url_by_asset: dict[str, str],
    warnings: list[dto.GenerationWarning], warnings_lock: Lock,
) -> ReportDraftResult:
    del warnings, warnings_lock
    # The V3 report is deliberately deterministic: the model may suggest prose
    # in future, but no unconstrained narrative is allowed to invent actions or
    # companions from scenery.
    return profile_engine.build_profile(
        analysis, requirements=requirements, memory_json=None,
        image_url_by_asset=image_url_by_asset,
    )


def _representative_asset_id(analysis: PhotoAnalysisResult) -> str:
    useful = [photo for photo in analysis.photos if photo.suitability != "unsuitable"]
    useful.sort(key=lambda photo: (photo.suitability != "good", -photo.analysis_confidence, not bool(photo.report_reason), photo.asset_id))
    return useful[0].asset_id


def _persist_results(
    *, user_id: str, operation_id: str, options: dto.GenerateOptions,
    requested_trip_id: str | None = None,
    location: str, date_label: str, start_date: str | None, end_date: str | None,
    source_asset_ids: list[str], postcard_renders: list[PostcardRender],
    report_draft: ReportDraftResult | None, report_cover_source_id: str,
    postcard_status: str, report_status: str, memory_status: str,
    warnings: list[dto.GenerationWarning], pending_memory_payload: dict | None,
    analysis: PhotoAnalysisResult | None = None,
    uploaded_photos: list[dto.UploadedPhoto] | None = None,
) -> dto.GenerateResult:
    group_dto: dto.PostcardGroup | None = None
    report_dto: dto.Report | None = None
    created_trip = requested_trip_id is None
    with session_scope() as session:
        trip = (
            trip_service.require_owned(session, user_id, requested_trip_id)
            if requested_trip_id
            else trip_service.create_in_session(
                session,
                user_id=user_id,
                location=location,
                start_date=start_date,
                end_date=end_date,
                date_label=date_label,
                cover_image=(postcard_renders[0].relative_path if postcard_renders else None),
            )
        )
        trip_id = trip.id
    if postcard_renders and postcard_status == "success":
        try:
            group_dto = _persist_postcard_branch(
                user_id=user_id, location=location, date_label=date_label,
                start_date=start_date, end_date=end_date,
                trip_id=trip_id,
                postcard_renders=postcard_renders,
            )
        except Exception as exc:  # noqa: BLE001
            postcard_status = "failed"
            warnings.append(_warning(
                "POSTCARD_SAVE_FAILED", "明信片已生成但保存失败，报告保存不受影响", "postcard", retryable=True,
            ))
            _discard([item.asset_id for item in postcard_renders])
            logger.warning("postcard persist failed: %s", type(exc).__name__)
    if report_draft is not None and report_status == "success":
        try:
            report_dto = _persist_report_branch(
                user_id=user_id, location=location, date_label=date_label,
                start_date=start_date, end_date=end_date,
                trip_id=trip_id,
                source_asset_ids=source_asset_ids, report_draft=report_draft,
                report_cover_source_id=report_cover_source_id,
            )
        except Exception as exc:  # noqa: BLE001
            report_status = "failed"
            warnings.append(_warning(
                "REPORT_SAVE_FAILED", "旅行报告保存失败，明信片保存不受影响", "report", retryable=True,
            ))
            logger.warning("report persist failed: %s", type(exc).__name__)
    if group_dto is None and report_dto is None:
        if created_trip:
            with session_scope() as session:
                empty_trip = session.get(TripEntity, trip_id)
                if empty_trip is not None:
                    session.delete(empty_trip)
        raise AIGenerationError("生成结果未能保存，请稍后重试")

    with session_scope() as session:
        trip = trip_service.require_owned(session, user_id, trip_id)
        trip_service.touch_from_artifact(
            trip,
            location=location,
            start_date=start_date,
            end_date=end_date,
            date_label=date_label,
            cover_image=(
                group_dto.cover_image
                if group_dto is not None
                else report_dto.cover_image if report_dto is not None else None
            ),
        )
        session.add(trip)
        session.flush()
        trip_dto = dto.TripSummary.model_validate(
            trip_service.get_trip(session, user_id, trip_id).model_dump()
        )

    if analysis is not None:
        try:
            with session_scope() as session:
                memory_service.record_trip_observation(
                    session,
                    user_id=user_id,
                    trip_id=trip_id,
                    operation_id=operation_id,
                    analysis=analysis,
                    photos=list(uploaded_photos or []),
                )
        except Exception:  # noqa: BLE001
            # The works are already saved. A missing observation must not turn a
            # successful report or postcard into a failed generation request.
            logger.exception(
                "failed to store photo observation",
                extra={"operation_id": operation_id, "trip_id": trip_id},
            )

    overall_status = "completed" if all(status != "failed" for status in (postcard_status, report_status, memory_status)) else "partial"
    result = dto.GenerateResult(
        postcard_group=group_dto, report=report_dto, operation_id=operation_id,
        trip=trip_dto,
        status=overall_status, postcard_status=postcard_status,
        report_status=report_status, memory_status=memory_status,
        warnings=list(warnings),
    )
    # Operation response and pending memory payload are committed together.
    with session_scope() as session:
        operation = session.get(GenerationOperation, operation_id)
        if operation is None or operation.user_id != user_id:
            raise InternalError("生成操作记录丢失")
        operation.status = result.status
        operation.postcard_status = postcard_status
        operation.report_status = report_status
        operation.memory_status = memory_status
        operation.trip_id = trip_id
        operation.pending_memory_payload = pending_memory_payload
        operation.response_json = result.model_dump(mode="json", by_alias=True)
        operation.updated_at = utcnow()
        session.add(operation)
    return result


def _persist_postcard_branch(
    *, user_id: str, location: str, date_label: str, start_date: str | None,
    end_date: str | None, trip_id: str, postcard_renders: list[PostcardRender],
) -> dto.PostcardGroup:
    with session_scope() as session:
        group = PostcardGroupEntity(
            id=id_service.new_postcard_group_id(), user_id=user_id,
            trip_id=trip_id,
            location=location, start_date=start_date, end_date=end_date,
            date_label=date_label, cover_image=postcard_renders[0].relative_path,
        )
        session.add(group)
        session.flush()
        entities: list[PostcardEntity] = []
        for render in postcard_renders:
            entity = PostcardEntity(
                id=id_service.new_postcard_id(), user_id=user_id, group_id=group.id,
                title=render.title, image_url=render.relative_path,
                sort_order=render.sort_order, source_asset_ids=render.source_asset_ids,
                render_mode=render.render_mode, prompt_version=postcard_renderer.PROMPT_VERSION,
            )
            session.add(entity)
            session.flush()
            entities.append(entity)
            file_asset_service.attach_with_reference(
                session, asset_id=render.asset_id, user_id=user_id,
                owner_type="postcard", owner_id=entity.id, role="postcard_image",
            )
        used_source_ids = list(dict.fromkeys(
            asset_id
            for render in postcard_renders
            for asset_id in render.source_asset_ids
        ))
        for asset_id in used_source_ids:
            file_asset_service.attach_with_reference(
                session, asset_id=asset_id, user_id=user_id,
                owner_type="postcard_group", owner_id=group.id, role="source_photo",
            )
        return mappers.postcard_group_to_dto(group, entities)


def _persist_report_branch(
    *, user_id: str, location: str, date_label: str, start_date: str | None,
    end_date: str | None, trip_id: str, source_asset_ids: list[str],
    report_draft: ReportDraftResult, report_cover_source_id: str,
) -> dto.Report:
    with session_scope() as session:
        cover_asset = session.get(FileAsset, report_cover_source_id)
        if cover_asset is None:
            raise InvalidParamError("报告封面照片不存在")
        report = ReportEntity(
            id=id_service.new_report_id(), user_id=user_id,
            trip_id=trip_id,
            location=location, start_date=start_date, end_date=end_date,
            date_label=date_label, cover_image=cover_asset.relative_path,
            personality_summary=report_draft.personality_summary,
            content=report_draft.content,
            chart_data=[point.model_dump() for point in report_draft.chart_data],
            profile_version=3,
            profile_data=report_draft.profile_data.model_dump(by_alias=True),
        )
        session.add(report)
        session.flush()
        file_asset_service.attach_with_reference(
            session, asset_id=cover_asset.id, user_id=user_id,
            owner_type="report", owner_id=report.id, role="report_cover",
        )
        for asset_id in source_asset_ids:
            file_asset_service.attach_with_reference(
                session, asset_id=asset_id, user_id=user_id,
                owner_type="report", owner_id=report.id, role="source_photo",
            )
        return mappers.report_to_dto(
            report,
            source_images=file_asset_service.list_reference_paths(
                session,
                user_id=user_id,
                owner_type="report",
                owner_id=report.id,
                role="source_photo",
            ),
        )


def _trip_fingerprint(
    analysis: PhotoAnalysisResult,
    content_hash_by_asset: dict[str, str] | None = None,
) -> str:
    payload = {
        "location": (analysis.overall_location or "").strip().lower(),
        "start_date": analysis.start_date, "end_date": analysis.end_date,
        "photo_dates": sorted({p.taken_date_guess for p in analysis.photos if p.taken_date_guess}),
        # Stable across idempotent retries and re-uploads of the same bytes;
        # distinct for metadata-free trips that contain different photos.
        "photo_content": sorted(
            (content_hash_by_asset or {}).get(p.asset_id, p.asset_id)
            for p in analysis.photos
        ),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _propose_memory_update(
    *, location: str, analysis: PhotoAnalysisResult | None, requirements: str,
) -> MemoryUpdateResult:
    del location, analysis
    clauses = [
        " ".join(part.strip().split())
        for part in re.split(r"[\n，。；;]+", requirements)
        if part.strip()
    ]
    concrete = list(dict.fromkeys(
        clause for clause in clauses if memory_service.is_actionable_requirement(clause)
    ))
    return MemoryUpdateResult(
        add_preferences=concrete,
        weaken_preferences=[],
        evidence_summary="用户明确填写的旅行要求",
        confidence=1.0,
        source_task="generate",
    )


def _retry_pending_memory(
    user_id: str,
    operation_id: str,
    request: dto.GenerateRequest,
    pending: dict,
    warnings: list[dto.GenerationWarning],
) -> str:
    """Retry only the unfinished memory stage; never recreate saved works."""
    if pending.get("stage") != "proposal":
        return _merge_pending_memory(user_id, operation_id, pending, warnings)
    try:
        update_result = _propose_memory_update(
            location="",
            analysis=None,
            requirements=(
                request.memory_requirements
                if request.memory_requirements is not None
                else request.requirements
            ),
        )
        merge_pending = {
            "stage": "merge",
            "add_preferences": update_result.add_preferences,
            "confidence": update_result.confidence,
            "trip_fingerprint": "",
        }
        with session_scope() as session:
            operation = session.get(GenerationOperation, operation_id)
            if operation is None or operation.user_id != user_id:
                raise InternalError("生成操作记录丢失")
            operation.pending_memory_payload = merge_pending
            operation.updated_at = utcnow()
            session.add(operation)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "memory proposal retry failed operation=%s reason=%s",
            operation_id,
            type(exc).__name__,
        )
        warnings.append(_warning(
            "MEMORY_PROPOSAL_FAILED",
            "内容已保留，但填写的要求还未加入旅行记忆；可稍后重试",
            "memory",
            retryable=True,
        ))
        return "failed"
    return _merge_pending_memory(user_id, operation_id, merge_pending, warnings)


def _merge_pending_memory(
    user_id: str, operation_id: str, pending: dict,
    warnings: list[dto.GenerationWarning],
) -> str:
    try:
        with session_scope() as session:
            operation = session.get(GenerationOperation, operation_id)
            trip_id = operation.trip_id if operation is not None else None
            memory_service.merge_memory_update(
                session, user_id=user_id,
                add_preferences=list(pending.get("add_preferences", [])),
                weaken_preferences=[], evidence_summary="", confidence=float(pending.get("confidence", 0)),
                source_type="explicit_requirement", source_id=operation_id,
                trip_fingerprint=trip_id,
            )
        return "success"
    except Exception as exc:  # noqa: BLE001
        logger.warning("memory merge failed operation=%s reason=%s", operation_id, type(exc).__name__)
        warnings.append(_warning(
            "MEMORY_MERGE_FAILED", "内容已保存，但填写的要求未加入旅行记忆", "memory", retryable=True,
        ))
        return "failed"


def _finalize_operation(operation_id: str, result: dto.GenerateResult) -> None:
    with session_scope() as session:
        operation = session.get(GenerationOperation, operation_id)
        if operation is None:
            return
        operation.status = result.status
        operation.postcard_status = result.postcard_status
        operation.report_status = result.report_status
        operation.memory_status = result.memory_status
        operation.pending_memory_payload = None if result.memory_status == "success" else operation.pending_memory_payload
        operation.response_json = result.model_dump(mode="json", by_alias=True)
        operation.updated_at = utcnow()
        session.add(operation)


def _discard(asset_ids: list[str]) -> None:
    if not asset_ids:
        return
    try:
        with session_scope() as session:
            file_asset_service.discard_temporary(session, list(set(asset_ids)))
    except Exception:  # noqa: BLE001
        logger.exception("failed to discard generated temporary assets")
