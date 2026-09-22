"""Build a concrete, photo-grounded travel report."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass

from app.ai.schemas import PhotoAnalysisResult, ReportCopyResult, ReportDraftResult
from app.models import dto
from app.services import memory_service

TRAIT_LABELS = {
    "environment": ("山野", "城市"),
    "depth": ("深潜", "广游"),
    "planning": ("随兴", "掌控"),
    "social": ("独享", "共游"),
}


@dataclass(frozen=True)
class ProfileHistory:
    """Compact, non-sensitive accumulation from previously saved reports."""

    previous_report_count: int
    motif_counts: dict[str, int]


def build_history_snapshot(profile_payloads: list[dict | None]) -> ProfileHistory:
    """Collect recurring scene motifs without treating them as personality facts."""
    motifs: Counter[str] = Counter()
    report_count = 0
    for payload in profile_payloads:
        if not isinstance(payload, dict):
            continue
        report_count += 1
        signature = payload.get("sceneSignature") or payload.get("scene_signature")
        tokens = signature.get("tokens") if isinstance(signature, dict) else None
        if not isinstance(tokens, list):
            tokens = payload.get("keywords")
        if isinstance(tokens, list):
            motifs.update(
                str(token).strip() for token in set(tokens) if str(token).strip()
            )
    return ProfileHistory(report_count, dict(motifs))


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
    history: ProfileHistory | None = None,
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

    archetype_id, archetype_name, persona_code, theme = _archetype(
        tags=tags, nature=nature, city=city, sample_quality=sample_quality,
    )

    overall_confidence = round(sum(t.confidence for t in traits) / len(traits), 2)
    scene_note = _scene_note(useful)
    scene_signature = _scene_signature(tags, useful, scene_note)
    evidence_highlights = _evidence_highlights(useful, image_url_by_asset or {})
    next_trip_experiments = _next_trip_experiments(scene_signature, tags)
    explicit_requirements = _explicit_requirement_clauses(requirements)
    history = history or ProfileHistory(0, {})
    journey_count = history.previous_report_count + 1
    returning_motifs = [
        token for token in scene_signature.tokens
        if history.motif_counts.get(token, 0) > 0
    ][:3]
    new_facets = [
        token for token in scene_signature.tokens
        if history.motif_counts.get(token, 0) == 0
    ][:3]
    profile_stage = _profile_stage(journey_count)
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
    portrait = _fallback_portrait(archetype_name, scene_note, scene_signature.tokens)
    track_update = _track_update(
        journey_count=journey_count,
        profile_stage=profile_stage,
        returning_motifs=returning_motifs,
        new_facets=new_facets,
    )
    modules = [
        dto.ProfileModule(title="本次主调", content=portrait),
        dto.ProfileModule(title="轨迹更新", content=track_update),
        dto.ProfileModule(title="仍未定稿", content=f"现有内容不足以判断{boundary}。"),
    ]
    requirement_note = "；".join(_explicit_requirement_clauses(requirements)) or "未填写"
    content = "\n\n".join(
        [
            f"本次旅程人格｜{archetype_name}",
            f"本次主调｜{portrait}",
            f"轨迹更新｜{track_update}",
            f"你填写的要求｜{requirement_note}",
        ]
    )
    profile = dto.TravelProfileData(
        archetype_id=archetype_id,
        archetype_name=archetype_name,
        persona_code=persona_code,
        slogan=_fallback_slogan(scene_signature.tokens),
        summary=portrait,
        spectrums=[
            dto.ProfileSpectrum(id=key, left_label=TRAIT_LABELS[key][0], right_label=TRAIT_LABELS[key][1], value=values[key])
            for key in ("environment", "depth", "planning", "social")
        ],
        keywords=_keywords(tags),
        modules=modules,
        strengths=[],
        watchouts=[],
        best_scenarios=scene_signature.tokens[:3],
        action_tips=[item.reason for item in next_trip_experiments],
        next_trip_inspiration=next_trip_experiments[0].reason,
        music_recommendation=None,
        travel_prescription=None,
        souvenir_line=_fallback_souvenir_line(scene_signature.tokens),
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
        journey_count=journey_count,
        profile_stage=profile_stage,
        returning_motifs=returning_motifs,
        new_facets=new_facets,
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
        personality_summary=archetype_name,
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


def apply_creative_copy(
    draft: ReportDraftResult,
    copy: ReportCopyResult,
) -> ReportDraftResult:
    """Apply model-written editorial copy without changing any scored fields."""
    profile = draft.profile_data
    track_module = next(
        (module for module in profile.modules if module.title == "轨迹更新"),
        None,
    )
    boundary_module = next(
        (module for module in profile.modules if module.title == "仍未定稿"),
        None,
    )
    modules = [
        dto.ProfileModule(title="本次主调", content=copy.portrait.strip()),
        dto.ProfileModule(title="最值得留下的一帧", content=copy.moment_line.strip()),
    ]
    if track_module is not None:
        modules.append(track_module)
    if boundary_module is not None:
        modules.append(boundary_module)

    experiments = list(profile.next_trip_experiments)
    if experiments:
        experiments[0] = experiments[0].model_copy(
            update={"title": copy.continue_title.strip()}
        )
    if len(experiments) > 1:
        experiments[1] = experiments[1].model_copy(
            update={"title": copy.contrast_title.strip()}
        )

    updated_profile = profile.model_copy(
        update={
            "archetype_name": copy.archetype_name.strip(),
            "slogan": copy.slogan.strip(),
            "summary": copy.portrait.strip(),
            "modules": modules,
            "souvenir_line": copy.souvenir_line.strip(),
            "next_trip_experiments": experiments,
        }
    )
    requirement_note = "；".join(profile.explicit_requirements) or "未填写"
    track_text = track_module.content if track_module is not None else "这是一次新的旅行记录。"
    content = "\n\n".join(
        [
            f"本次旅程人格｜{copy.archetype_name.strip()}",
            f"本次主调｜{copy.portrait.strip()}",
            f"画面留声｜{copy.souvenir_line.strip()}",
            f"轨迹更新｜{track_text}",
            f"你填写的要求｜{requirement_note}",
        ]
    )
    return draft.model_copy(
        update={
            "personality_summary": copy.archetype_name.strip(),
            "content": content,
            "profile_data": updated_profile,
        }
    )


def _archetype(
    *, tags: Counter, nature: int, city: int, sample_quality: str,
) -> tuple[str, str, str, str]:
    """Choose a vivid current-trip editorial lens, never a permanent trait."""
    if sample_quality == "low" and not any(tags.values()):
        return "open_draft", "未定稿旅人", "OPEN · 01", "ocean_blue"
    if tags["culture"] > max(nature, city, tags["food"]):
        return "archive_reader", "旧城索引员", "ARCHIVE · 07", "museum_gold"
    if tags["food"] > max(nature, city, tags["culture"]):
        return "local_sampler", "街味采样者", "TASTE · 05", "sunset_orange"
    if tags["coast"] >= max(1, tags["mountain"], tags["night"]):
        return "tide_collector", "潮线收藏家", "TIDE · 03", "ocean_blue"
    if tags["mountain"] >= max(1, tags["coast"], tags["night"]):
        return "ridge_reader", "山脊定向者", "RIDGE · 06", "forest_light"
    if tags["night"] >= max(1, tags["street"], tags["culture"]):
        return "night_mapper", "夜色测绘员", "NIGHT · 08", "night_purple"
    if nature > city:
        return "open_land_reader", "开阔地读者", "FIELD · 02", "forest_light"
    if city > 0:
        return "street_editor", "街区切片师", "BLOCK · 04", "city_neon"
    return "route_observer", "沿途观察员", "ROUTE · 00", "ocean_blue"


def _profile_stage(journey_count: int) -> str:
    if journey_count <= 1:
        return "初见"
    if journey_count <= 3:
        return "轮廓浮现"
    if journey_count <= 6:
        return "风格成形"
    return "坐标清晰"


def _track_update(
    *, journey_count: int, profile_stage: str,
    returning_motifs: list[str], new_facets: list[str],
) -> str:
    if journey_count == 1:
        anchors = "、".join(new_facets) or "这组画面"
        return f"第 1 次记录，先把{anchors}收入你的旅行词典。"
    pieces = [f"第 {journey_count} 次记录，档案进入“{profile_stage}”阶段"]
    if returning_motifs:
        pieces.append(f"再次出现：{'、'.join(returning_motifs)}")
    if new_facets:
        pieces.append(f"本次新增：{'、'.join(new_facets)}")
    return "；".join(pieces) + "。"


def _fallback_portrait(
    archetype_name: str, scene_note: str, tokens: list[str],
) -> str:
    del archetype_name
    anchor = "、".join(tokens[:2]) or "沿途场景"
    scene = _complete_within(scene_note, 54).rstrip("。！？；，、：")
    portrait = f"{scene}。这一程以{anchor}为观看坐标，记下画面里最有辨识度的层次与节奏。"
    return _complete_within(portrait, 100)


def _fallback_slogan(tokens: list[str]) -> str:
    anchor = tokens[0] if tokens else "沿途场景"
    return f"沿着{anchor}的线索，把下一站看得更具体"


def _fallback_souvenir_line(tokens: list[str]) -> str:
    anchor = tokens[0] if tokens else "沿途风景"
    return f"把{anchor}留在这一程的页边"


def _scene_note(useful: list) -> str:
    if not useful:
        return "暂无可用照片内容"
    summaries = [photo.scene_summary.strip() for photo in useful if photo.scene_summary.strip()]
    if summaries:
        return _complete_within("；".join(summaries[:2]), 72).rstrip("。！？；，、：")
    facts = [fact.strip() for photo in useful for fact in photo.observed_facts if fact.strip()]
    if facts:
        return _complete_within("、".join(dict.fromkeys(facts)), 72).rstrip("。！？；，、：")
    return "这组照片记录了旅行中的场景"


def _complete_within(text: str, limit: int) -> str:
    """Clip generated/fallback prose at a natural boundary, never mid-word."""
    cleaned = re.sub(r"\s+", "", text.strip())
    if len(cleaned) <= limit:
        return cleaned
    candidate = cleaned[:limit]
    for marks in ("。！？；", "，、："):
        cut = max(candidate.rfind(mark) for mark in marks)
        if cut >= max(12, limit // 2):
            return candidate[:cut + 1]
    return candidate[: limit - 1].rstrip("，、：；") + "。"


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
