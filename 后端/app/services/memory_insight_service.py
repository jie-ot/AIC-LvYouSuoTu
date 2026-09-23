"""Build explainable travel history and cross-trip observations.

Facts stay attached to trips. Repeated behaviour becomes an observation, never
an active planning preference until the user explicitly confirms it.
"""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import date
from typing import Any

from sqlmodel import Session, select

from app.models import dto
from app.models.file_asset_reference import FileAssetReference
from app.models.plan import Plan
from app.models.postcard_group import PostcardGroup
from app.models.report import Report
from app.models.trip import Trip
from app.services import trip_service


TRAVEL_TYPE_LABELS = {
    "coast": "海滨海岛",
    "nature": "山水自然",
    "culture": "历史人文",
    "city": "城市漫游",
    "food": "在地饮食",
}

TRAVEL_TYPE_EVIDENCE = {
    "coast": "海岸、海岛或港湾",
    "nature": "山地、公园或自然景观",
    "culture": "博物馆、历史建筑或老城街区",
    "city": "城市地标、街区或夜景",
    "food": "当地餐饮与小吃",
}

TRAVEL_TYPE_PLANNING_TEXT = {
    "coast": "规划时优先考虑海岸、海岛或港湾类地点",
    "nature": "规划时优先考虑山地、公园或自然景观",
    "culture": "规划时优先考虑博物馆、历史建筑或老城街区",
    "city": "规划时优先考虑城市地标、街区或夜景",
    "food": "规划时保留当地餐饮与小吃体验",
}

SCENE_TO_TYPE = {
    "coast": "coast",
    "mountain": "nature",
    "nature": "nature",
    "culture": "culture",
    "street": "city",
    "city": "city",
    "night": "city",
    "food": "food",
}

TYPE_KEYWORDS = {
    "coast": (
        "海滨", "海岸", "海岛", "沙滩", "港湾", "渔港", "滨海", "海景",
        "三亚", "大连", "青岛", "厦门", "海口", "舟山", "北海", "泉州石狮",
    ),
    "nature": (
        "山", "湖", "森林", "峡谷", "草原", "公园", "景区", "地质", "瀑布",
        "九寨沟", "徒步", "自然", "湿地", "岛",
    ),
    "culture": (
        "博物馆", "历史", "古城", "古镇", "古街", "故宫", "纪念馆", "遗址",
        "陵", "寺", "祠", "文化", "民国", "建筑", "老城",
    ),
    "city": (
        "城市", "商圈", "街区", "夜景", "广场", "地标", "步行街", "咖啡",
        "上海", "北京", "成都", "重庆", "南京",
    ),
    "food": (
        "美食", "小吃", "餐饮", "海鲜", "火锅", "烧烤", "本地菜", "家常菜",
        "餐厅", "饭店", "咖啡",
    ),
}

NON_VISIT_KEYWORDS = (
    "机场", "火车站", "高铁站", "酒店", "民宿", "办理入住", "办理退房",
    "车站", "南站", "北站", "东站", "西站", "码头",
    "餐厅", "饭店", "酒楼", "用餐", "午餐", "晚餐", "早餐",
)

ABSTRACT_FACT_TERMS = (
    "偏好", "喜欢", "人格", "画像", "光影", "氛围感", "松弛感", "治愈", "审美",
)


def _clean(value: object) -> str:
    return " ".join(str(value or "").strip().split())


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _date_label_end(value: str | None) -> date | None:
    matches = re.findall(r"(\d{4})[./-](\d{1,2})[./-](\d{1,2})", value or "")
    if not matches:
        return None
    year, month, day = matches[-1]
    try:
        return date(int(year), int(month), int(day))
    except ValueError:
        return None


def _safe_int(value: object) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _safe_float(value: object) -> float:
    try:
        return max(0.0, float(value or 0))
    except (TypeError, ValueError):
        return 0.0


def _trip_state(trip: Trip, photo_count: int) -> tuple[str, str]:
    end = _parse_date(trip.end_date or trip.start_date) or _date_label_end(trip.date_label)
    if end and end >= date.today():
        return "planned", "待出发"
    if end or photo_count:
        return "recorded", "已记录"
    return "undated", "日期待补"


def _iter_schedules(plan: Plan) -> list[dict[str, Any]]:
    raw = plan.itinerary_data if isinstance(plan.itinerary_data, dict) else {}
    result: list[dict[str, Any]] = []
    for day_item in raw.get("itinerary", []):
        if not isinstance(day_item, dict):
            continue
        for schedule in day_item.get("schedules", []):
            if isinstance(schedule, dict):
                result.append(schedule)
    return result


def _plan_facts(plans: list[Plan]) -> tuple[list[str], str | None, str, int, int]:
    places: list[str] = []
    searchable: list[str] = []
    total_days = 0
    attraction_count = 0
    for plan in plans:
        raw = plan.itinerary_data if isinstance(plan.itinerary_data, dict) else {}
        days = [item for item in raw.get("itinerary", []) if isinstance(item, dict)]
        total_days += len(days)
        food = raw.get("food_recommendations", [])
        if isinstance(food, list):
            searchable.extend(_clean(item) for item in food[:4])
        for schedule in _iter_schedules(plan):
            name = _clean(schedule.get("place_name") or schedule.get("placeName"))
            activity = _clean(schedule.get("activity"))
            tags = schedule.get("tags", [])
            tag_text = " ".join(_clean(tag) for tag in tags) if isinstance(tags, list) else ""
            is_attraction = (
                schedule.get("map_role") == "attraction"
                or schedule.get("mapRole") == "attraction"
                or (
                    name
                    and not any(term in name for term in NON_VISIT_KEYWORDS)
                    and not any(term in tag_text for term in (
                        "交通", "接驳", "入住", "正餐", "晚餐", "午餐", "早餐",
                        "美食", "小吃", "餐饮", "咖啡",
                    ))
                )
            )
            if not is_attraction:
                continue
            searchable.extend((name, activity, tag_text))
            attraction_count += 1
            if name and name not in places:
                places.append(name)
    pace = None
    if total_days and attraction_count:
        average = attraction_count / total_days
        value = f"{average:.1f}".rstrip("0").rstrip(".")
        pace = f"{total_days} 天 · 日均约 {value} 个主要地点"
    return places[:5], pace, " ".join(searchable), total_days, attraction_count


def _type_scores(text: str, scene_tags: set[str]) -> dict[str, int]:
    scores = {
        key: sum(text.count(word) for word in words)
        for key, words in TYPE_KEYWORDS.items()
    }
    for scene_tag in scene_tags:
        mapped = SCENE_TO_TYPE.get(scene_tag)
        if mapped:
            scores[mapped] += 3
    return scores


def _travel_types(text: str, scene_tags: set[str]) -> list[str]:
    scores = _type_scores(text, scene_tags)
    ordered = sorted(
        (item for item in scores.items() if item[1] > 0),
        key=lambda item: (-item[1], list(TRAVEL_TYPE_LABELS).index(item[0])),
    )
    return [TRAVEL_TYPE_LABELS[key] for key, _score in ordered[:3]]


def _safe_observed_facts(raw: object) -> list[str]:
    if not isinstance(raw, list):
        return []
    result: list[str] = []
    for item in raw:
        value = _clean(item)
        if not value or len(value) > 36 or any(term in value for term in ABSTRACT_FACT_TERMS):
            continue
        if value not in result:
            result.append(value)
    return result[:3]


def _photo_assets_by_trip(
    session: Session,
    user_id: str,
    groups: list[PostcardGroup],
    reports: list[Report],
) -> dict[str, set[str]]:
    group_trip = {item.id: item.trip_id for item in groups if item.trip_id}
    report_trip = {item.id: item.trip_id for item in reports if item.trip_id}
    assets: dict[str, set[str]] = defaultdict(set)
    refs = session.exec(
        select(FileAssetReference).where(
            FileAssetReference.user_id == user_id,
            FileAssetReference.role == "source_photo",
        )
    ).all()
    for ref in refs:
        trip_id = (
            group_trip.get(ref.owner_id)
            if ref.owner_type == "postcard_group"
            else report_trip.get(ref.owner_id) if ref.owner_type == "report" else None
        )
        if trip_id:
            assets[trip_id].add(ref.asset_id)
    return assets


def scene_source_photos(
    observations: dict[str, Any], photo_trip_ids: set[str], pattern_key: str,
) -> list[dto.TravelMemoryPhotoEvidence]:
    """Expose only photo assets tagged with this specific observed scene."""
    rows: list[dto.TravelMemoryPhotoEvidence] = []
    seen: set[tuple[str, str]] = set()
    for trip_id in sorted(photo_trip_ids):
        snapshot = observations.get(trip_id)
        scene_evidence = snapshot.get("scene_evidence") if isinstance(snapshot, dict) else None
        if not isinstance(scene_evidence, dict):
            continue
        for tag, evidence_list in scene_evidence.items():
            if SCENE_TO_TYPE.get(str(tag)) != pattern_key or not isinstance(evidence_list, list):
                continue
            for evidence in evidence_list:
                if not isinstance(evidence, dict):
                    continue
                asset_id = str(evidence.get("asset_id") or "")
                image_url = str(evidence.get("image_url") or "")
                pair = (trip_id, asset_id)
                if asset_id and image_url.startswith("/static/uploads/") and pair not in seen:
                    seen.add(pair)
                    rows.append(dto.TravelMemoryPhotoEvidence(
                        trip_id=trip_id, asset_id=asset_id, image_url=image_url,
                    ))
    return rows[:12]


def build_context(
    session: Session,
    user_id: str,
    memory_json: dict[str, Any] | None,
) -> tuple[dto.TravelMemoryStats, list[dto.TravelMemoryFootprint], list[dto.TravelMemoryPattern]]:
    trips = list(session.exec(
        select(Trip).where(Trip.user_id == user_id).order_by(Trip.updated_at.desc())
    ).all())
    plans = list(session.exec(select(Plan).where(Plan.user_id == user_id)).all())
    groups = list(session.exec(select(PostcardGroup).where(PostcardGroup.user_id == user_id)).all())
    reports = list(session.exec(select(Report).where(Report.user_id == user_id)).all())
    plans_by_trip: dict[str, list[Plan]] = defaultdict(list)
    for plan in plans:
        if plan.trip_id:
            plans_by_trip[plan.trip_id].append(plan)
    photo_assets = _photo_assets_by_trip(session, user_id, groups, reports)

    raw_observations = (memory_json or {}).get("trip_observations", {})
    observations = raw_observations if isinstance(raw_observations, dict) else {}
    footprints: list[dto.TravelMemoryFootprint] = []
    plan_type_support: dict[str, set[str]] = defaultdict(set)
    photo_type_support: dict[str, set[str]] = defaultdict(set)
    plan_pace_rows: list[tuple[str, int, int]] = []
    photo_full_day_trip_ids: list[str] = []

    for trip in trips:
        trip_plans = plans_by_trip.get(trip.id, [])
        places, plan_pace, plan_text, plan_days, attraction_count = _plan_facts(trip_plans)
        observation = observations.get(trip.id, {})
        observation = observation if isinstance(observation, dict) else {}
        scene_tags = {
            str(tag)
            for tag in observation.get("scene_tags", [])
            if str(tag) in SCENE_TO_TYPE
        }
        location_labels = _safe_observed_facts(observation.get("photo_location_labels"))
        facts = _safe_observed_facts(observation.get("observed_facts"))
        stored_photo_count = _safe_int(observation.get("photo_count"))
        photo_count = max(len(photo_assets.get(trip.id, set())), stored_photo_count)
        photo_day_count = _safe_int(observation.get("photo_day_count"))
        same_day_span = _safe_float(observation.get("longest_same_day_span_hours"))
        if same_day_span >= 7:
            photo_full_day_trip_ids.append(trip.id)
        display_title = trip_service.default_title(trip.location, trip.date_label) if trip_service.is_placeholder_title(trip.title) else trip.title
        text = " ".join(filter(None, (_clean(trip.location), _clean(display_title), plan_text)))
        type_labels = _travel_types(text, scene_tags)
        scores = _type_scores(plan_text, set())
        for key, score in scores.items():
            if score > 0:
                plan_type_support[key].add(trip.id)
        for scene_tag in scene_tags:
            mapped = SCENE_TO_TYPE.get(scene_tag)
            if mapped:
                photo_type_support[mapped].add(trip.id)
        if plan_days and attraction_count:
            plan_pace_rows.append((trip.id, plan_days, attraction_count))

        source_labels: list[str] = []
        if trip_plans:
            source_labels.append(f"{len(trip_plans)} 份规划")
        if photo_count:
            source_labels.append(f"{photo_count} 张照片")
        if not source_labels:
            source_labels.append("旅行记录")
        pace_label = plan_pace
        if same_day_span >= 2:
            span_value = f"{same_day_span:.1f}".rstrip("0").rstrip(".")
            photo_pace = f"同日照片最长间隔约 {span_value} 小时"
            pace_label = f"{plan_pace} · {photo_pace}" if plan_pace else photo_pace
        elif photo_day_count >= 2:
            photo_pace = f"照片记录跨 {photo_day_count} 天"
            pace_label = f"{plan_pace} · {photo_pace}" if plan_pace else photo_pace
        state, state_label = _trip_state(trip, photo_count)
        footprints.append(dto.TravelMemoryFootprint(
            id=f"footprint_{trip.id}",
            trip_id=trip.id,
            title=display_title,
            location=trip.location,
            date_label=trip.date_label,
            cover_image=trip.cover_image,
            state=state,
            state_label=state_label,
            source_labels=source_labels,
            travel_types=type_labels,
            highlights=list(dict.fromkeys([*location_labels, *facts, *places]))[:5],
            pace_label=pace_label,
            photo_count=photo_count,
            plan_count=len(trip_plans),
            has_photo_observation=trip.id in observations,
        ))

    confirmed_ids = {
        _clean(item.get("source_pattern_id"))
        for item in (memory_json or {}).get("items", [])
        if isinstance(item, dict) and item.get("state") == "saved"
    }
    patterns: list[dto.TravelMemoryPattern] = []
    for key in TRAVEL_TYPE_LABELS:
        plan_ids = plan_type_support.get(key, set())
        photo_ids = photo_type_support.get(key, set())
        support_ids = plan_ids | photo_ids
        # One photo trip is useful as an observation. A plan pattern needs two
        # independent trips before it earns space in the memory screen.
        if len(support_ids) < 2 and not photo_ids:
            continue
        if photo_ids and plan_ids:
            source_kind = "combined"
            content = f"{len(support_ids)} 次旅行的照片或规划中出现{TRAVEL_TYPE_EVIDENCE[key]}。"
            source_labels = [f"{len(photo_ids)} 次照片记录", f"{len(plan_ids)} 次旅行的规划"]
        elif photo_ids:
            source_kind = "photos"
            content = f"{len(photo_ids)} 次旅行的照片中出现{TRAVEL_TYPE_EVIDENCE[key]}。"
            source_labels = [f"{len(photo_ids)} 次照片记录"]
        else:
            source_kind = "plans"
            content = f"{len(plan_ids)} 次旅行的规划包含{TRAVEL_TYPE_EVIDENCE[key]}。"
            source_labels = [f"{len(plan_ids)} 次旅行的规划"]
        pattern_id = f"pattern_travel_type_{key}"
        patterns.append(dto.TravelMemoryPattern(
            id=pattern_id,
            title=TRAVEL_TYPE_LABELS[key],
            content=content,
            category="food" if key == "food" else "attractions",
            source_kind=source_kind,
            support_count=len(support_ids),
            source_trip_ids=sorted(support_ids),
            photo_source_trip_ids=sorted(photo_ids),
            source_photos=scene_source_photos(observations, photo_ids, key),
            source_labels=source_labels,
            # Even one photo trip can support a suggestion for the user to
            # affirm. It remains absent from planning until they confirm it.
            confirmable=bool(photo_ids) or len(support_ids) >= 2,
            confirmed=pattern_id in confirmed_ids,
            planning_text=TRAVEL_TYPE_PLANNING_TEXT[key],
        ))

    if len(plan_pace_rows) >= 2:
        total_days = sum(days for _trip_id, days, _count in plan_pace_rows)
        total_attractions = sum(count for _trip_id, _days, count in plan_pace_rows)
        average = total_attractions / total_days
        rounded = max(1, round(average))
        value = f"{average:.1f}".rstrip("0").rstrip(".")
        pattern_id = "pattern_plan_daily_pace"
        patterns.append(dto.TravelMemoryPattern(
            id=pattern_id,
            title="每天安排多少",
            content=f"{len(plan_pace_rows)} 次旅行的规划平均每天安排 {value} 个主要地点。",
            category="pace",
            source_kind="plans",
            support_count=len(plan_pace_rows),
            source_trip_ids=[trip_id for trip_id, _days, _count in plan_pace_rows],
            photo_source_trip_ids=[],
            source_labels=[f"{len(plan_pace_rows)} 次旅行的规划"],
            confirmable=True,
            confirmed=pattern_id in confirmed_ids,
            planning_text=f"规划时每天安排约 {rounded} 个主要地点",
        ))

    if len(photo_full_day_trip_ids) >= 2:
        pattern_id = "pattern_photo_full_day"
        patterns.append(dto.TravelMemoryPattern(
            id=pattern_id,
            title="全天游玩",
            content=f"{len(photo_full_day_trip_ids)} 次旅行都有同日拍摄间隔 7 小时以上的照片。",
            category="pace",
            source_kind="photos",
            support_count=len(photo_full_day_trip_ids),
            source_trip_ids=photo_full_day_trip_ids,
            photo_source_trip_ids=photo_full_day_trip_ids,
            source_labels=[f"{len(photo_full_day_trip_ids)} 次照片记录"],
            confirmable=True,
            confirmed=pattern_id in confirmed_ids,
            planning_text="规划时可保留从上午到傍晚的完整游玩时段",
        ))

    source_priority = {"photos": 0, "combined": 1, "plans": 2}
    patterns.sort(key=lambda item: (
        item.confirmed,
        source_priority[item.source_kind],
        -item.support_count,
        item.title,
    ))
    distinct_places = {
        re.sub(r"市$", "", _clean(trip.location))
        for trip in trips
        if _clean(trip.location) and _clean(trip.location) not in {"未知地点", "未知目的地"}
    }
    stats = dto.TravelMemoryStats(
        trip_count=len(trips),
        place_count=len(distinct_places),
        photo_count=sum(item.photo_count for item in footprints),
        plan_count=len(plans),
    )
    return stats, footprints, patterns
