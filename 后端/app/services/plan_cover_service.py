"""One text-to-image cover for a plan-only trip.

After a plan is saved onto a trip that still has no cover, call Seedream once.
Two or more core sights become one continuous landscape that links them in
visit order. A single sight, or no named sight, becomes a pencil sketch of
that sight or of the destination city. This path does not review the image
and does not generate a second one.
"""

from __future__ import annotations

import hashlib

from app.ai.clients import ark_image_client
from app.core.business_logging import log_event
from app.db.session import session_scope
from app.models.base import utcnow
from app.models.itinerary import ItineraryData, Schedule
from app.services import file_asset_service, schedule_kind, storage_service, trip_service

COVER_IMAGE_SIZE = "1792x1024"
_MAX_LINKED_SIGHTS = 4
_GENERIC_PLACES = frozenset({
    "景区", "景点", "市区", "市中心", "城区", "目的地", "酒店", "住宿",
    "餐厅", "午餐", "晚餐", "早餐", "自由活动", "未知目的地", "未知地点",
})
_NO_TEXT = (
    "景点或城市名称只用来决定画什么，禁止写进画面。"
    "不要任何文字、路牌、招牌、水印、签名、Logo、邮票、边框或地图标注，"
    "也不要把游客画成主体。"
)


def attach_cover(*, user_id: str, trip_id: str, plan_id: str, data: ItineraryData) -> str | None:
    """Generate one cover and store it on the trip. Returns the relative path."""
    prompt = build_cover_prompt(data)
    log_event(
        "plan_cover_prompt",
        status="ready",
        plan_id=plan_id,
        trip_id=trip_id,
        prompt_hash=hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:16],
        prompt_chars=len(prompt),
        size=COVER_IMAGE_SIZE,
        attempts=1,
    )
    result = ark_image_client.generate_image(
        prompt=prompt,
        size=COVER_IMAGE_SIZE,
        max_attempts=1,
    )
    if not result.image_url:
        raise RuntimeError("plan cover model returned no image")
    relative_path = storage_service.build_plan_cover_relative_path("jpg")
    stored = storage_service.download_to_static(result.image_url, relative_path)
    try:
        with session_scope() as session:
            trip = trip_service.require_owned(session, user_id, trip_id)
            if trip.cover_image:
                storage_service.delete_physical_file(stored.relative_path)
                return None
            asset = file_asset_service.create_temporary(
                session,
                user_id=user_id,
                relative_path=stored.relative_path,
                mime_type=stored.mime_type,
                size_bytes=stored.size_bytes,
                usage_type="generated_plan_cover",
            )
            file_asset_service.attach_with_reference(
                session,
                asset_id=asset.id,
                user_id=user_id,
                owner_type="plan",
                owner_id=plan_id,
                role="plan_attachment",
            )
            trip.cover_image = stored.relative_path
            trip.updated_at = utcnow()
            session.add(trip)
    except Exception:
        storage_service.delete_physical_file(stored.relative_path)
        raise
    log_event(
        "plan_cover_saved",
        status="success",
        plan_id=plan_id,
        trip_id=trip_id,
        relative_path=stored.relative_path,
    )
    return stored.relative_path


def build_cover_prompt(data: ItineraryData) -> str:
    """Choose a linked-sights cover or a single-subject sketch."""
    highlights = _short_highlights(data)
    sights = _select_sights(_core_sights(data), highlights)
    destination = _destination(data)
    theme = _theme_clause(data)
    if len(sights) >= 2:
        return _linked_prompt(destination, sights, theme)
    subject = sights[0] if sights else destination
    return _sketch_prompt(destination, subject, theme, city_only=not sights)


def _linked_prompt(destination: str, sights: list[str], theme: str) -> str:
    where = f"目的地是{destination}。" if destination else ""
    sequence = "、".join(sights)
    return (
        "画一张 16:9 横版旅行封面。把下列核心景点放进同一张连续画面，"
        "按游玩顺序从左到右串联，用小路、水面、街巷或视线连成一程。"
        "不要分格，不要拼贴，不要漫画分镜。"
        f"{where}景点依次是：{sequence}。"
        "每处只画最能被认出来的建筑、地貌或街巷轮廓，近处一处、其余渐渐远去，"
        "尺度有主次，光线统一。媒介是带纸纹的淡彩旅行插画，铅笔线稿清楚，颜色克制，留出安静的天空。"
        f"{theme}{_NO_TEXT}"
    )


def _sketch_prompt(destination: str, subject: str, theme: str, *, city_only: bool) -> str:
    if city_only and destination:
        focus = (
            f"只画{destination}最能被认出来的城市轮廓："
            "天际线、江岸或最具代表性的建筑群，作为一张城市素描。"
        )
    elif city_only:
        focus = "画一座让人想起远行的城市天际轮廓素描，结构清楚，不要编造具体地名。"
    else:
        setting = (
            f"背景可以轻轻带出{destination}的城市气质，但主角只有这一处。"
            if destination and destination not in subject
            else "画面里只有这一处主角。"
        )
        focus = f"只画最核心的景点「{subject}」，选取它最经典、最能被一眼认出的角度。{setting}"
    return (
        "画一张 16:9 横版封面。媒介是素描纸上的铅笔与淡墨建筑速写："
        "结构线清楚，排线克制，纸色留白，单一侧光，不要鲜艳颜色。"
        f"{focus}{theme}{_NO_TEXT}"
    )


def _core_sights(data: ItineraryData) -> list[str]:
    names: list[str] = []
    for day in data.itinerary:
        for schedule in day.schedules:
            if schedule_kind.classify_schedule(schedule) != "attraction":
                continue
            _add_name(names, _attraction_name(schedule))
        for daily_map in day.daily_maps:
            for point in daily_map.points:
                if point.kind == "attraction":
                    _add_name(names, point.name)
    return names


def _select_sights(names: list[str], highlights: list[str]) -> list[str]:
    featured = [name for name in names if _mentioned(name, highlights)]
    others = [name for name in names if name not in featured]
    chosen: list[str] = []
    for name in [*featured, *others]:
        if name not in chosen:
            chosen.append(name)
        if len(chosen) >= _MAX_LINKED_SIGHTS:
            break
    kept = set(chosen)
    return [name for name in names if name in kept]


def _attraction_name(schedule: Schedule) -> str | None:
    for raw in (schedule.place_name, schedule.map_label):
        name = _clean(raw)
        if _usable(name):
            return name
    activity = _clean(schedule.activity)
    if activity and len(activity) <= 16 and _usable(activity):
        return activity
    return None


def _short_highlights(data: ItineraryData) -> list[str]:
    summary = data.experience_summary
    if summary is None:
        return []
    highlights: list[str] = []
    for item in summary.highlights:
        text = _clean(item)
        if text and len(text) <= 18 and _usable(text):
            highlights.append(text)
    return highlights


def _destination(data: ItineraryData) -> str:
    name = _clean(data.trip_info.destination)
    if not _usable(name):
        return ""
    return name[:40]


def _theme_clause(data: ItineraryData) -> str:
    summary = data.experience_summary
    theme = _clean(summary.trip_theme) if summary is not None else ""
    if not theme or len(theme) > 24:
        return ""
    return f"气氛贴近「{theme}」，但不要把这句话画成文字。"


def _mentioned(name: str, highlights: list[str]) -> bool:
    return any(name in item or item in name for item in highlights)


def _add_name(names: list[str], raw: str | None) -> None:
    name = _clean(raw)
    if _usable(name) and name not in names and len(name) <= 32:
        names.append(name)


def _usable(name: str) -> bool:
    return bool(name) and name not in _GENERIC_PLACES


def _clean(value: str | None) -> str:
    return " ".join((value or "").split())
