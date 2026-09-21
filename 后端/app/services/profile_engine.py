"""Build a concrete, photo-grounded travel report."""

from __future__ import annotations

import re
from collections import Counter

from app.ai.schemas import PhotoAnalysisResult, ReportDraftResult
from app.models import dto
from app.services import memory_service

TRAIT_LABELS = {
    "environment": ("山野", "城市"),
    "depth": ("深潜", "广游"),
    "planning": ("随兴", "掌控"),
    "social": ("独享", "共游"),
}


def _explicit_score(text: str, left_words: tuple[str, ...], right_words: tuple[str, ...]) -> int | None:
    left = sum(_affirmed_count(text, word) for word in left_words)
    right = sum(_affirmed_count(text, word) for word in right_words)
    if left == right == 0:
        return None
    return max(15, min(85, 50 + (right - left) * 15))


def _affirmed_count(text: str, word: str) -> int:
    count = 0
    for match in re.finditer(re.escape(word), text):
        prefix = text[max(0, match.start() - 8):match.start()]
        if re.search(
            r"(?:不和|不要|不想|不愿|避免|无需|拒绝|不需要|别|勿|不)"
            r"[^，。；;\n]{0,8}$",
            prefix,
        ):
            continue
        count += 1
    return count


def _trait_score(
    requirements: str,
    records: list[tuple[str, str]],
    left_words: tuple[str, ...],
    right_words: tuple[str, ...],
) -> tuple[int | None, list[str]]:
    refs: list[str] = []
    chunks: list[str] = []
    if any(word in requirements for word in (*left_words, *right_words)):
        chunks.append(requirements)
        refs.append("request:explicit")
    for text, ref in records:
        if any(word in text for word in (*left_words, *right_words)):
            chunks.append(text)
            refs.append(ref)
    return _explicit_score(" ".join(chunks), left_words, right_words), list(dict.fromkeys(refs))


def _preference_polarity_score(
    requirements: str,
    records: list[tuple[str, str]],
    words: tuple[str, ...],
) -> int | None:
    """Score only wishes the user stated or confirmed, never photo contents."""
    score = 0
    for text in (requirements, *(value for value, _ref in records)):
        score += sum(
            memory_service.preference_term_polarity(text, word)
            for word in words
        )
    if score == 0:
        return None
    return max(15, min(85, 50 + score * 15))


def build_profile(
    analysis: PhotoAnalysisResult,
    *,
    requirements: str,
    memory_json: dict | None,
    image_url_by_asset: dict[str, str] | None = None,
) -> ReportDraftResult:
    useful = [p for p in analysis.photos if p.suitability != "unsuitable"]
    # A report belongs to one trip. Long-term memory must not change what this
    # trip's photos say; only requirements entered for this generation apply.
    del memory_json
    memory_records: list[tuple[str, str]] = []
    evidence_refs = list(dict.fromkeys(p.asset_id for p in useful))
    tags = Counter(tag for photo in useful for tag in photo.scene_tags)
    if not tags:
        corpus = " ".join(p.scene_summary for p in useful)
        tags.update(
            {
                "nature": sum(corpus.count(w) for w in ("山", "海", "湖", "森林", "日落", "自然")),
                "city": sum(corpus.count(w) for w in ("城市", "街", "建筑", "夜景")),
                "culture": sum(corpus.count(w) for w in ("博物馆", "历史", "文化", "古城")),
                "food": sum(corpus.count(w) for w in ("美食", "餐厅", "小吃", "咖啡")),
            }
        )

    sample_quality = "high" if len(useful) >= 8 else "medium" if len(useful) >= 3 else "low"
    nature = tags["nature"] + tags["coast"] + tags["mountain"]
    city = tags["city"] + tags["street"] + tags["night"]
    environment = 50 if nature == city == 0 else max(15, min(85, 50 + (city - nature) * 12))
    environment_refs = [
        photo.asset_id
        for photo in useful
        if set(photo.scene_tags) & {"nature", "coast", "mountain", "city", "street", "night"}
    ]
    if not environment_refs and (nature or city):
        environment_refs = evidence_refs
    environment_supported = bool(environment_refs)
    depth, depth_refs = _trait_score(
        requirements, memory_records,
        ("深度游", "深入一地", "长时间体验"),
        ("广游", "多地旅行", "打卡多个城市", "一次多城"),
    )
    planning, planning_refs = _trait_score(
        requirements, memory_records,
        ("随兴", "自由安排", "临时决定"),
        ("详细计划", "提前预订", "明确时间"),
    )
    social, social_refs = _trait_score(
        requirements, memory_records,
        ("一个人", "独自", "独行"),
        ("同行", "和朋友", "和家人", "亲子", "结伴"),
    )
    food, _food_refs = _trait_score(
        requirements, memory_records,
        ("不安排美食", "不关注餐饮", "不以吃为主"),
        ("美食", "小吃", "餐厅", "本地菜", "在地饮食", "咖啡馆"),
    )
    pace, _pace_refs = _trait_score(
        requirements, memory_records,
        ("赶行程", "紧凑行程", "高强度行程"),
        ("慢节奏", "不要太赶", "留出午休", "留有缓冲", "轻松行程"),
    )
    nature_preference = _preference_polarity_score(
        requirements,
        memory_records,
        ("自然景观", "山野", "海边", "海岸", "森林", "湖畔"),
    )
    culture_preference = _preference_polarity_score(
        requirements,
        memory_records,
        ("人文", "文化", "历史", "博物馆", "古城", "老城"),
    )

    values = {
        "environment": environment if environment_supported else 50,
        "depth": depth if depth is not None else 50,
        "planning": planning if planning is not None else 50,
        "social": social if social is not None else 50,
    }
    supported = {
        "environment": environment_supported,
        "depth": depth is not None,
        "planning": planning is not None,
        "social": social is not None,
    }
    trait_refs = {
        "environment": environment_refs if environment_supported else [],
        "depth": depth_refs if depth is not None else [],
        "planning": planning_refs if planning is not None else [],
        "social": social_refs if social is not None else [],
    }
    if sample_quality == "low":
        values = {key: 50 for key in values}
        supported = {key: False for key in supported}
        trait_refs = {key: [] for key in trait_refs}

    traits = [
        dto.ProfileTraitAssessment(
            id=trait_id,
            value=values[trait_id],
            confidence=(min(0.85, 0.35 + len(useful) * 0.08) if trait_id == "environment" else 0.75)
            if supported[trait_id]
            else 0.0,
            evidence_refs=trait_refs[trait_id],
            assessment="supported" if supported[trait_id] else "undetermined",
        )
        for trait_id in ("environment", "depth", "planning", "social")
    ]

    if sample_quality == "low":
        archetype_id, archetype_name, theme = "photo_report", "旅行照片", "ocean_blue"
    elif tags["culture"] > max(nature, city, tags["food"]):
        archetype_id, archetype_name, theme = "culture_report", "人文与历史", "museum_gold"
    elif nature > city:
        archetype_id, archetype_name, theme = "nature_report", "自然风景", "forest_light"
    elif city > 0:
        archetype_id, archetype_name, theme = "city_report", "城市与街区", "city_neon"
    else:
        archetype_id, archetype_name, theme = "photo_report", "旅行照片", "ocean_blue"

    overall_confidence = round(sum(t.confidence for t in traits) / len(traits), 2)
    scene_note = _scene_note(useful)
    scene_signature = _scene_signature(tags, useful, scene_note)
    evidence_highlights = _evidence_highlights(useful, image_url_by_asset or {})
    next_trip_experiments = _next_trip_experiments(scene_signature, tags)
    explicit_requirements = _explicit_requirement_clauses(requirements)
    unknown_names = [
        {
            "environment": "稳定场景倾向",
            "depth": "旅行深度",
            "planning": "规划方式",
            "social": "同行偏好",
        }[key]
        for key in ("environment", "depth", "planning", "social")
        if not supported[key]
    ]
    boundary = "、".join(unknown_names) or "其他特质"
    modules = [
        dto.ProfileModule(title="照片内容", content=scene_note),
        dto.ProfileModule(title="说明", content=f"这些照片没有提供足够信息判断{boundary}。"),
    ]
    requirement_note = "；".join(_explicit_requirement_clauses(requirements)) or "未填写"
    content = "\n\n".join(
        [
            f"照片印象｜{scene_note}",
            f"你填写的要求｜{requirement_note}",
            "说明｜仅根据本次旅行的照片和你填写的要求生成。",
        ]
    )
    profile = dto.TravelProfileData(
        archetype_id=archetype_id,
        archetype_name=archetype_name,
        persona_code="PHOTO",
        slogan=scene_note,
        summary=scene_note,
        spectrums=[
            dto.ProfileSpectrum(id=key, left_label=TRAIT_LABELS[key][0], right_label=TRAIT_LABELS[key][1], value=values[key])
            for key in ("environment", "depth", "planning", "social")
        ],
        keywords=_keywords(tags),
        modules=modules,
        strengths=[],
        watchouts=[],
        best_scenarios=[],
        action_tips=[item.reason for item in next_trip_experiments],
        next_trip_inspiration=next_trip_experiments[0].reason,
        music_recommendation=None,
        travel_prescription=None,
        souvenir_line=None,
        visual_theme=theme,
        sample_quality=sample_quality,
        confidence=overall_confidence,
        traits=traits,
        scope_note=(
            "照片较少，内容仅供参考。"
            if sample_quality == "low"
            else "仅根据本次旅行的照片和你填写的要求生成。"
        ),
        scene_signature=scene_signature,
        evidence_highlights=evidence_highlights,
        next_trip_experiments=next_trip_experiments,
        explicit_requirements=explicit_requirements,
    )
    chart_values = {
        # The radar uses only stated/confirmed wishes.  Visible scenery stays
        # in sceneSignature/evidenceHighlights and must not become preference.
        "自然探索": nature_preference if nature_preference is not None else 50,
        "人文体验": culture_preference if culture_preference is not None else 50,
        "美食偏好": food if food is not None else 50,
        "慢节奏": pace if pace is not None else 50,
        "社交意愿": values["social"] if supported["social"] else 50,
    }
    if sample_quality == "low":
        chart_values = {key: 50 for key in chart_values}
    chart = [dto.ReportChartPoint(dimension=key, value=value) for key, value in chart_values.items()]
    return ReportDraftResult(
        location=(analysis.overall_location or "未知地点").strip() or "未知地点",
        start_date=analysis.start_date,
        end_date=analysis.end_date,
        personality_summary=scene_signature.title,
        content=content,
        chart_data=chart,
        profile_data=profile,
    )


def apply_canonical_fields(draft: ReportDraftResult, analysis: PhotoAnalysisResult) -> ReportDraftResult:
    """Never let generated prose override canonical photo metadata."""
    return draft.model_copy(
        update={
            "location": (analysis.overall_location or "未知地点").strip() or "未知地点",
            "start_date": analysis.start_date,
            "end_date": analysis.end_date,
        }
    )


def _scene_note(useful: list) -> str:
    if not useful:
        return "暂无可用照片内容"
    facts = [fact.strip() for photo in useful for fact in photo.observed_facts if fact.strip()]
    if facts:
        return "、".join(dict.fromkeys(facts))[:90]
    summaries = [photo.scene_summary.strip() for photo in useful if photo.scene_summary.strip()]
    return "；".join(summaries[:2])[:90] or "这组照片记录了旅行中的场景"


def _explicit_requirement_clauses(requirements: str) -> list[str]:
    signals = (
        "深度", "广游", "多地", "多城", "随兴", "自由安排", "临时决定",
        "计划", "预订", "时间", "一个人", "独自", "独行", "同行", "朋友",
        "家人", "亲子", "结伴", "美食", "小吃", "餐厅", "本地菜", "咖啡",
        "自然景观", "山野", "海边", "海岸", "森林", "湖畔", "人文", "文化",
        "历史", "博物馆", "古城", "老城", "夜景", "城市", "街区",
        "节奏", "赶", "午休", "缓冲", "轻松",
        "无障碍", "轮椅", "电梯", "过敏", "忌口", "不吃",
        "楼梯", "婴儿床", "婴儿", "老人", "老年", "孕妇", "儿童", "推车", "拐杖", "爬坡",
        "预算", "价格", "费用", "酒店", "住宿", "民宿",
        "交通", "高铁", "火车", "飞机", "航班", "驾车", "自驾", "换乘",
    )
    clauses = [
        clause.strip()
        for clause in re.split(r"[\n，。；;]+", requirements)
        if clause.strip() and any(word in clause for word in signals)
    ]
    return list(dict.fromkeys(clause[:80] for clause in clauses))


def _scene_signature(
    tags: Counter,
    useful: list,
    scene_note: str,
) -> dto.SceneSignature:
    labels = {
        "nature": "自然场景",
        "city": "城市空间",
        "culture": "人文与历史",
        "food": "在地饮食",
        "night": "夜景",
        "coast": "滨水空间",
        "mountain": "山野景观",
        "street": "街区细节",
    }
    tokens = list(
        dict.fromkeys(
            labels[key]
            for key, count in tags.most_common()
            if count and key in labels
        )
    )[:4]
    if not tokens:
        tokens.append("可见场景")
    if len(tokens) >= 2:
        title = " · ".join(tokens[:2])
    else:
        title = tokens[0]
    description = (
        f"这组照片主要记录了：{scene_note}。"
    )
    return dto.SceneSignature(
        title=title,
        tokens=tokens,
        description=description,
        evidence_refs=list(dict.fromkeys(photo.asset_id for photo in useful)),
    )


def _evidence_highlights(
    useful: list,
    image_url_by_asset: dict[str, str],
) -> list[dto.EvidenceHighlight]:
    highlights: list[dto.EvidenceHighlight] = []
    for photo in useful:
        facts = [fact.strip() for fact in photo.observed_facts if fact.strip()]
        observed = "、".join(dict.fromkeys(facts))[:80]
        if not observed:
            observed = photo.scene_summary.strip()[:80]
        if not observed:
            continue
        highlights.append(
            dto.EvidenceHighlight(
                asset_id=photo.asset_id,
                image_url=image_url_by_asset.get(photo.asset_id),
                observed_fact=observed,
                trait_id="scene",
                contribution="这项内容来自照片中可见的场景。",
            )
        )
        if len(highlights) == 3:
            break
    return highlights


def _next_trip_experiments(
    signature: dto.SceneSignature,
    tags: Counter,
) -> list[dto.NextTripExperiment]:
    anchor = signature.tokens[0]
    nature = tags["nature"] + tags["coast"] + tags["mountain"]
    city = tags["city"] + tags["street"] + tags["night"]
    contrast = (
        "城市街区"
        if nature > city
        else "自然开放空间"
        if city > nature
        else "与当前画面不同的场景"
    )
    refs = signature.evidence_refs[:3]
    return [
        dto.NextTripExperiment(
            kind="continue",
            title="找相似场景",
            reason=f"以照片中的{anchor}作为条件查找目的地。",
            planning_prompt=(
                f"请推荐 3 个适合拍摄{anchor}的目的地，等我选择后再规划行程。"
            ),
            evidence_refs=refs,
        ),
        dto.NextTripExperiment(
            kind="contrast",
            title="看看不同场景",
            reason=f"从{contrast}开始浏览其他目的地。",
            planning_prompt=(
                f"请推荐 3 个以{contrast}为特色的目的地，等我选择后再规划行程。"
            ),
            evidence_refs=refs,
        ),
    ]


def _keywords(tags: Counter) -> list[str]:
    labels = {
        "nature": "自然场景", "city": "城市空间", "culture": "人文与历史",
        "food": "当地饮食", "night": "夜景", "coast": "水岸",
        "mountain": "山野景观", "street": "街区细节",
    }
    values = list(dict.fromkeys(labels[key] for key, count in tags.most_common() if count and key in labels))[:3]
    honest_fallbacks = ["旅行照片"]
    for value in honest_fallbacks:
        if len(values) >= 3:
            break
        if value not in values:
            values.append(value)
    return values[:5]
