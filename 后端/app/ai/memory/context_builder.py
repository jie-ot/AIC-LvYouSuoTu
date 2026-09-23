"""Assemble bounded model inputs for planning and photo-based creation.

Saved travel memory is available only to planning. Photo analysis, reports and
postcards use the current request and current photos, never long-term memory.
"""

from __future__ import annotations

import json
from typing import Any

from app.ai.schemas import PhotoAnalysisResult, PostcardSelectionResult
from app.models.itinerary import ItineraryData


def build_planning_user_text(
    *,
    message: str,
    context: ItineraryData | None,
    memory_summary: str,
    fact_pack: dict[str, Any] | None = None,
) -> str:
    """Compose the planning input from cumulative requirements + latest plan."""
    parts: list[str] = []
    parts.append(f"【用户已保存的旅行记忆】\n{memory_summary}")
    parts.append(f"【累计用户需求（含本轮新增要求）】\n{message}")
    if context is not None:
        compact_context = context.model_dump(exclude={"memory_context", "memory_basis", "planning_snapshot"})
        for day in compact_context.get("itinerary", []):
            day.pop("daily_maps", None)
        parts.append(
            "【最新完整行程 context（只保留上一版规划；请在此基础上重写，未涉及部分保持不变）】\n"
            + json.dumps(compact_context, ensure_ascii=False)
        )
    else:
        parts.append("【当前完整行程 context】\nnull（首轮，请新建完整行程）")
    if fact_pack is not None:
        parts.append(
            "【受控事实包 TravelFactPack】\n"
            "事实数组为空是正常状态，不代表目的地没有相关信息或已经完成查询。"
            "只有 status=ok 的 Function Calling 返回才能作为事实写入行程；"
            "所有成功返回的工具事实采用同一可信规则，不再划分来源等级。"
            "没有工具结果时不得编造班次、票价、余票、天气、地点或路线数据。\n"
            + json.dumps(fact_pack, ensure_ascii=False)
        )
    return "\n\n".join(parts)


def build_report_copy_user_text(*, brief: dict[str, Any], requirements: str) -> str:
    """Give the copy editor the computed 旅格 and the only facts it may cite."""
    return (
        f"【用户对这一程的描述与要求】\n{requirements or '（用户没有填写）'}\n\n"
        "【后端算好的旅格与事实（数值与类型名不可改写）】\n"
        + json.dumps(brief, ensure_ascii=False)
    )


def build_postcard_creative_user_text(
    *,
    analysis: PhotoAnalysisResult,
    selection: PostcardSelectionResult,
    selected_asset_ids: list[str],
    requirements: str,
    memory_summary: str,
) -> str:
    """Compose the multimodal creative brief input for selected photos.

    Images are attached after this text in exactly ``selected_asset_ids`` order.
    The explicit manifest lets the model associate each original image with the
    backend asset IDs used by each selected postcard slot.
    """
    image_manifest = "\n".join(
        f"图片{idx}：asset_id={asset_id}"
        for idx, asset_id in enumerate(selected_asset_ids, start=1)
    )
    selection_manifest = "\n".join(
        f"明信片{idx}：source_asset_ids="
        + json.dumps(item.source_asset_ids, ensure_ascii=False)
        for idx, item in enumerate(selection.items, start=1)
    )
    del memory_summary
    return (
        f"【本次制作要求】\n{requirements}\n\n"
        "【已选明信片与参考照片】\n"
        f"{selection_manifest}\n\n"
        "【随消息附加的原图顺序】\n"
        f"{image_manifest}\n\n"
        "【已选照片的语义信息】\n"
        + json.dumps(analysis.model_dump(), ensure_ascii=False)
    )


def build_photo_analysis_user_text(
    *,
    photo_metas: list[dict],
    requirements: str,
    memory_summary: str,
    batch_index: int | None = None,
    batch_total: int | None = None,
) -> str:
    """Compose user text for photo analysis.

    Includes a per-photo manifest so the model echoes the exact backend
    `asset_id` for each image (images are attached in the same order). Without
    this, the model has no way to return our internal asset ids.

    When ``batch_total > 1``, clarifies that only the current subset is in
    scope so the model does not expect photos from other batches.
    """
    del memory_summary  # Photo observation must not be biased by past preferences.
    lines = [
        f"本次共有 {len(photo_metas)} 张照片，按顺序与下方图片一一对应。",
        "请在输出的 photos[] 中，对每张照片使用下面给定的 asset_id（严禁臆造其它 ID）：",
    ]
    for idx, meta in enumerate(photo_metas, start=1):
        taken = meta.get("taken_at") or "未提供"
        if meta.get("place"):
            loc = f"{meta['place']}（GPS 逆地理）"
        elif meta.get("location"):
            loc = f"{meta['location']}（坐标未解析出地名，可结合画面推断城市）"
        else:
            loc = "未提供"
        lines.append(
            f"{idx}. asset_id={meta.get('asset_id')}，相机当地拍摄时间={taken}，"
            f"拍摄地点={loc}"
        )
    manifest = "\n".join(lines)
    parts = [f"【本次生成需求】\n{requirements}"]
    if batch_index is not None and batch_total is not None and batch_total > 1:
        parts.append(
            f"【分批说明】本次为第 {batch_index}/{batch_total} 批，仅包含本批 "
            f"{len(photo_metas)} 张照片。请只分析本批图片，不得遗漏本批任一 asset_id；"
            "overall_location / start_date / end_date 仅反映本批照片的综合推断，"
            "后端会将多批结果合并为完整 PhotoAnalysisResult。"
        )
    parts.append(f"【照片清单（asset_id 必须原样使用）】\n{manifest}")
    return "\n\n".join(parts)
