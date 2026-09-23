"""Bounded, source-preserving memory selection for one planning request.

Only saved and enabled items enter the model. Current explicit requirements
win over stored memory. The final basis is a literal text match in the
validated itinerary, not an assertion about the model's internal reasoning.
"""

from __future__ import annotations

import json
import re
from typing import Any

from app.models.dto import PlanningBrief
from app.models.itinerary import (
    ItineraryData,
    PlanningMemoryBasis,
    PlanningMemoryContext,
    PlanningMemoryItem,
    PlanningMemoryPhoto,
)
from app.services import memory_insight_service, memory_service


MAX_ITEMS = 6
MAX_PROMPT_CHARS = 1500
_HARD_CONSTRAINT = re.compile(r"过敏|忌口|必须|只能|只坐|不要|不能|避免|轮椅|无障碍|最多|至少")
_NEGATIVE = re.compile(r"不|别|避免|避开|排除|拒绝|禁止|过敏|忌口")
_BASIS_TERMS = (
    "历史街区", "自然景观", "海岸线", "博物馆", "美术馆", "老城区", "高铁站",
    "当地菜", "地方菜", "咖啡馆", "海鲜", "日落", "海边", "海岸", "山野",
    "湖畔", "森林", "小吃", "高铁", "地铁", "飞机", "火车", "民宿",
    "午休", "步行", "安静", "摄影", "拍照", "展览", "老城", "街区",
)
_GENERIC_MATCHES = {"行程", "旅行", "旅游", "规划", "安排", "地方", "体验", "可以", "喜欢", "偏好", "用户", "本次", "景点", "酒店", "住宿", "交通"}
_GENERAL_CATEGORIES = frozenset({"transport", "hotel", "pace", "food", "accessibility", "budget"})
_RELEVANCE_TERMS = (*_BASIS_TERMS, "自然", "文化", "历史", "古镇", "亲子", "徒步")
_CONFLICT_TERMS = (*_RELEVANCE_TERMS, "打车", "海鲜", "早起", "晚起", "民宿", "酒店")
_EXCLUSIVE = re.compile(r"只能|只坐|只住|必须|一定|首选|优先")
_TRANSPORT_MODES = {"rail": ("高铁", "动车", "火车"), "air": ("飞机", "航班"), "car": ("自驾", "打车", "网约车")}
_LODGING_MODES = {"hotel": ("酒店",), "homestay": ("民宿",)}
_SCOPED_PLACE = re.compile(r"(?:在|到|去)([\u4e00-\u9fff]{2,8})(?=住|吃|玩|游|看|时|期间)")
_SCENE_BASIS_TERMS = {
    "coast": ("海边", "海岸", "海岛", "沙滩", "海湾", "港湾", "渔港", "滨海"),
    "nature": ("森林", "山地", "湖畔", "湿地", "瀑布", "峡谷", "草原"),
    "culture": ("博物馆", "历史建筑", "老城", "古镇", "遗址", "古街"),
    "city": ("城市地标", "街区", "夜景"),
    "food": ("本地菜", "小吃", "当地餐饮", "海鲜"),
}


def _current_clauses(brief: PlanningBrief | None, current_message: str) -> list[str]:
    texts = [current_message]
    if brief is not None:
        texts.extend(filter(None, (
            brief.transport_preference, brief.lodging_preference, brief.budget,
            brief.detail_requirements, *brief.constraints, *brief.interests,
        )))
    return [clause for value in texts for clause in memory_service.preference_clauses(value)]


def _mode(text: str, mapping: dict[str, tuple[str, ...]]) -> str | None:
    return next((mode for mode, terms in mapping.items() if any(term in text for term in terms)), None)


def _conflicts(memory_text: str, category: str, current_clauses: list[str]) -> bool:
    for clause in current_clauses:
        # Opposite instructions about the same concrete object, e.g. no
        # seafood versus eat seafood, override stored memory.
        for term in _CONFLICT_TERMS:
            if term not in memory_text or term not in clause:
                continue
            stored_polarity = memory_service.preference_term_polarity(memory_text, term)
            current_polarity = memory_service.preference_term_polarity(clause, term)
            if stored_polarity * current_polarity < 0:
                return True
        if category == "pace":
            relaxed = ("慢", "宽松", "不赶", "留白")
            intense = ("紧凑", "高强度", "赶场", "密集")
            if (any(word in memory_text for word in relaxed) and any(word in clause for word in intense)) or (
                any(word in memory_text for word in intense) and any(word in clause for word in relaxed)
            ):
                return True
        # Different transport/lodging types conflict only when one side sets
        # an exclusive or priority choice. Avoiding taxis is compatible with
        # preferring a train; two unrelated hotel wishes can coexist.
        if _NEGATIVE.search(memory_text) or _NEGATIVE.search(clause):
            continue
        mapping = _TRANSPORT_MODES if category == "transport" else _LODGING_MODES if category == "hotel" else None
        if mapping and _EXCLUSIVE.search(memory_text + clause):
            old_mode, new_mode = _mode(memory_text, mapping), _mode(clause, mapping)
            if old_mode and new_mode and old_mode != new_mode:
                return True
    return False


def _scoped_places(text: str) -> list[str]:
    return [
        re.sub(r"(?:旅行|旅游)$", "", place).removesuffix("市")
        for place in _SCOPED_PLACE.findall(text)
    ]


def _scene_matches(raw_item: dict, destinations: list[str], interests: list[str]) -> bool:
    pattern_id = str(raw_item.get("source_pattern_id") or "")
    prefix = "pattern_travel_type_"
    if not pattern_id.startswith(prefix):
        return False
    scene_type = pattern_id[len(prefix):]
    terms = memory_insight_service.TYPE_KEYWORDS.get(scene_type, ())
    target = " ".join([*destinations, *interests])
    return any(len(term) >= 2 and term in target for term in terms)


def _prompt_payload(items: list[PlanningMemoryItem]) -> dict[str, Any]:
    def model_item(item: PlanningMemoryItem) -> dict[str, Any]:
        row: dict[str, Any] = {
            "id": item.id, "text": item.text, "category": item.category,
            "sourceKind": item.source_kind,
        }
        trip_ids = list(dict.fromkeys([
            *([item.source_trip_id] if item.source_trip_id else []),
            *item.source_trip_ids,
        ]))[:2]
        if trip_ids:
            row["sourceTripIds"] = trip_ids
        photo_ids = list(dict.fromkeys(photo.asset_id for photo in item.source_photos))[:2]
        if photo_ids:
            row["sourcePhotoAssetIds"] = photo_ids
        return row

    return {
        "priority": "本次用户明确需求高于历史记忆；冲突时忽略历史记忆。来源 ID 只供追溯，不能推断偏好强度。照片观察未确认前不得当作偏好。",
        "selected": [model_item(item) for item in items],
    }


def prompt_text(context: PlanningMemoryContext) -> str:
    if not context.enabled or not context.selected:
        return json.dumps({"selected": [], "priority": "仅依据本次用户明确需求。"}, ensure_ascii=False)
    return json.dumps(_prompt_payload(context.selected), ensure_ascii=False, separators=(",", ":"))


def select_memory(
    memory_json: dict[str, Any] | None,
    *,
    brief: PlanningBrief | None,
    current_message: str,
    use_memory: bool = True,
    context_destinations: list[str] | None = None,
    excluded_memory_ids: list[str] | None = None,
) -> PlanningMemoryContext:
    raw = memory_json if isinstance(memory_json, dict) else {}
    observations = raw.get("trip_observations") if isinstance(raw.get("trip_observations"), dict) else {}
    items = raw.get("items") if isinstance(raw.get("items"), list) else []
    candidates = [
        item for item in items
        if isinstance(item, dict)
        and item.get("state") == "saved"
        and item.get("enabled", True)
        and str(item.get("text") or "").strip()
    ]
    enabled = bool(use_memory and raw.get("enabled", True))
    excluded_ids = list(dict.fromkeys(excluded_memory_ids or []))
    if not enabled:
        return PlanningMemoryContext(enabled=False, skipped_count=len(candidates), excluded_ids=excluded_ids)

    current_clauses = _current_clauses(brief, current_message)
    destinations = [*(brief.destinations if brief else []), *(context_destinations or [])]
    interests = brief.interests if brief else []
    query = " ".join(filter(None, [
        current_message,
        " ".join(destinations),
        " ".join(interests),
    ]))
    ranked: list[PlanningMemoryItem] = []
    for raw_item in candidates:
        text = " ".join(str(raw_item.get("text") or "").strip().split())
        category = str(raw_item.get("category") or "other")
        item_id = str(raw_item.get("id") or "").strip()
        if not item_id or item_id in excluded_ids or len(text) > 240 or _conflicts(text, category, current_clauses):
            continue
        scopes = _scoped_places(text)
        if scopes and not any(
            scope and any(scope in destination or destination in scope for destination in destinations)
            for scope in scopes
        ):
            continue
        destination_match = any(destination in text for destination in destinations if len(destination) >= 2)
        interest_match = any(term in text and term in query for term in _RELEVANCE_TERMS)
        scene_match = _scene_matches(raw_item, destinations, interests)
        if category not in _GENERAL_CATEGORIES and not (destination_match or interest_match or scene_match):
            continue
        score = 1
        if _HARD_CONSTRAINT.search(text):
            score += 3
        if category != "other" and any(
            word in query for word in memory_service.CATEGORY_KEYWORDS.get(category, ())
        ):
            score += 2
        # A literal destination or activity overlap is useful but never turns
        # a photo observation into a preference; those are absent from items.
        if destination_match:
            score += 3
        if interest_match:
            score += 2
        if scene_match:
            score += 2
        trip_ids = raw_item.get("source_trip_ids")
        photo_ids = raw_item.get("photo_source_trip_ids")
        pattern_id = str(raw_item.get("source_pattern_id") or "")
        pattern_prefix = "pattern_travel_type_"
        source_photos = (
            memory_insight_service.scene_source_photos(
                observations,
                {str(value) for value in photo_ids if value} if isinstance(photo_ids, list) else set(),
                pattern_id[len(pattern_prefix):],
            )[:4]
            if pattern_id.startswith(pattern_prefix)
            else []
        )
        ranked.append(PlanningMemoryItem(
            id=item_id,
            text=text,
            category=category,
            source_kind=str(raw_item.get("source_kind") or "manual"),
            source_pattern_id=pattern_id or None,
            source_trip_id=str(raw_item["source_trip_id"]) if raw_item.get("source_trip_id") else None,
            source_trip_title=str(raw_item["source_trip_title"]) if raw_item.get("source_trip_title") else None,
            source_trip_ids=[str(value) for value in trip_ids if value] if isinstance(trip_ids, list) else [],
            source_photos=[PlanningMemoryPhoto(
                trip_id=photo.trip_id, asset_id=photo.asset_id, image_url=photo.image_url,
            ) for photo in source_photos],
            relevance_score=score,
        ))
    ranked.sort(key=lambda item: (-item.relevance_score, item.id))
    # Two enabled saved instructions can contradict each other. With no
    # current user resolution, feeding either one is arbitrary; omit both.
    ranked = [
        item for item in ranked
        if not any(
            other.id != item.id and other.category == item.category and (
                _conflicts(item.text, item.category, [other.text])
                or _conflicts(other.text, other.category, [item.text])
            )
            for other in ranked
        )
    ]
    selected: list[PlanningMemoryItem] = []
    for item in ranked:
        if len(selected) >= MAX_ITEMS:
            break
        trial = [*selected, item]
        payload = json.dumps(_prompt_payload(trial), ensure_ascii=False, separators=(",", ":"))
        if len(payload) <= MAX_PROMPT_CHARS:
            selected.append(item)
    return PlanningMemoryContext(
        enabled=True,
        selected=selected,
        skipped_count=len(candidates) - len(selected),
        excluded_ids=excluded_ids,
    )


def _literal_match(memory_text: str, schedule_text: str) -> str | None:
    if _NEGATIVE.search(memory_text):
        # Absence of a forbidden item cannot prove a schedule obeyed a rule.
        return None
    for term in _BASIS_TERMS:
        if term in memory_text and term in schedule_text:
            return term
    memory_clean = re.sub(r"\s+", "", memory_text)
    schedule_clean = re.sub(r"\s+", "", schedule_text)
    matches = [
        match.group(0) for match in re.finditer(r"[\u4e00-\u9fff]{3,}", memory_clean)
    ]
    for phrase in matches:
        for length in range(min(len(phrase), 10), 2, -1):
            for start in range(len(phrase) - length + 1):
                term = phrase[start:start + length]
                if term not in _GENERIC_MATCHES and term in schedule_clean:
                    return term
    return None


def build_basis(
    itinerary: ItineraryData,
    context: PlanningMemoryContext,
    *,
    retained_facts: dict[str, Any] | None = None,
    max_items: int = 3,
) -> list[PlanningMemoryBasis]:
    """Link selected memory to the strongest visible schedule text match."""
    if not context.enabled:
        return []
    result: list[PlanningMemoryBasis] = []
    for memory in context.selected:
        matches: list[tuple[tuple[int, int, int, int], PlanningMemoryBasis]] = []
        for day_index, day in enumerate(itinerary.itinerary):
            for schedule_index, schedule in enumerate(day.schedules):
                schedule_text = " ".join(filter(None, [schedule.activity, schedule.place_name, schedule.transport]))
                term = _literal_match(memory.text, schedule_text)
                match_kind = "literal"
                if not term and memory.source_pattern_id:
                    prefix = "pattern_travel_type_"
                    if memory.source_pattern_id.startswith(prefix):
                        scene_type = memory.source_pattern_id[len(prefix):]
                        term = next((word for word in _SCENE_BASIS_TERMS.get(scene_type, ()) if word in schedule_text), None)
                        match_kind = "scene"
                if not term:
                    continue
                fact_refs = [ref for ref in schedule.fact_refs if ref in (retained_facts or {})]
                basis = PlanningMemoryBasis(
                    memory_id=memory.id,
                    schedule_id=schedule.id,
                    matched_term=term,
                    match_kind=match_kind,
                    schedule_excerpt=schedule.activity[:120],
                    fact_refs=fact_refs,
                )
                # A sourced attraction is easier to inspect than an incidental
                # mention of the same scene in a meal or transfer note. Facts
                # verify the place, not whether memory caused this choice.
                score = (bool(fact_refs), match_kind == "literal", -day_index, -schedule_index)
                matches.append((score, basis))
        if matches:
            result.append(max(matches, key=lambda entry: entry[0])[1])
        if len(result) >= max_items:
            break
    return result
