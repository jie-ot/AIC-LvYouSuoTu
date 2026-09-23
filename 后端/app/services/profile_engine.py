"""旅格引擎：把一次旅行的照片算成一份可分享、可比对的旅行人格。

Four axes are measured from the trip itself — 景 (nature ↔ city), 行 (dwell ↔
roam), 时 (morning ↔ night) and 观 (vista ↔ close-up). Their poles form a
four-character code such as 山游晨远 that indexes one of 16 fixed archetypes, so
two travellers' reports stay comparable. A numeric persona vector is stored with
the report so a future matching feature can read it; that matching is not part
of the report. The language model only rewrites copy on top of these results,
and each of its fields is validated and replaced on its own if it fails.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime

from app.ai.schemas import ReportCopyResult, ReportDraftResult
from app.models import dto
from app.services.journey_features import NATURE_TAGS, URBAN_TAGS, JourneyFeatures, JourneyPhoto

PROFILE_VERSION = 5

# id, dimension name, left code, right code, left word, right word.
# Codes stay one character so the seal can read 城游夜远. The words on the
# spectrum are complete on their own, the way 外向 and 内向 are.
AXES: tuple[tuple[str, str, str, str, str, str], ...] = (
    ("scene", "景物偏好", "山", "城", "山野", "城池"),
    ("pace", "行进节奏", "栖", "游", "栖居", "游走"),
    ("time", "出镜时辰", "晨", "夜", "晨光", "夜色"),
    ("lens", "观看尺度", "远", "近", "远景", "近物"),
)


@dataclass(frozen=True)
class Archetype:
    id: str
    name: str
    tagline: str
    word: str
    word_note: str


ARCHETYPES: dict[str, Archetype] = {
    "山游晨远": Archetype("dawn_ridge", "逐日巡山人", "天一亮就出发，把远山一座座收进取景框", "远", "越走越远，越看越阔"),
    "山游晨近": Archetype("trail_gleaner", "山径拾光者", "走得很远，也肯为一朵花蹲下来", "拾", "路上的小东西都算数"),
    "山游夜远": Archetype("star_drifter", "星野夜行客", "白天赶路，天黑以后才等来正片", "野", "天黑了，风景才开场"),
    "山游夜近": Archetype("breeze_collector", "晚风拾趣人", "一路向野，入夜还要把细节拍够", "趣", "越晚越有意思"),
    "山栖晨远": Archetype("mist_keeper", "晨雾守山人", "认准一座山，看它从雾里醒过来", "静", "一座山看够一个早晨"),
    "山栖晨近": Archetype("field_notes", "草木笔记派", "不赶路，一草一木都记进相册", "细", "近处自有山河"),
    "山栖夜远": Archetype("moon_waiter", "等月亮的人", "挑好一处风景，从黄昏守到夜深", "候", "好风景值得等"),
    "山栖夜近": Archetype("lamp_lodger", "山居灯下客", "在山里住下，把夜晚过得很具体", "暖", "山夜有灯，人就安心"),
    "城游晨远": Archetype("skyline_hunter", "天际线猎手", "一座座城赶早去，先把全景拿下", "阔", "城市要从高处读起"),
    "城游晨近": Archetype("corner_sampler", "街角采样员", "换一座城，就重新采集一遍街角", "逛", "好玩的都在拐角"),
    "城游夜远": Archetype("neon_navigator", "霓虹夜航员", "城市亮灯以后，才是你的出发时间", "亮", "灯一亮，城就醒了"),
    "城游夜近": Archetype("night_forager", "夜巷寻味家", "夜越深，巷子越窄，镜头越近", "味", "城的滋味在夜里"),
    "城栖晨远": Archetype("slow_reader", "一城慢读者", "一座城不急着翻页，从日出读到日落", "读", "一座城，慢慢看"),
    "城栖晨近": Archetype("alley_lens", "巷口慢镜头", "守着一条巷子，拍出一整天的光影", "慢", "慢下来，细节就来了"),
    "城栖夜远": Archetype("lantern_gazer", "灯火凭栏人", "守一处高点，看整座城慢慢亮起来", "望", "灯火是城市的签名"),
    "城栖夜近": Archetype("night_archivist", "夜色收藏家", "把一座城的夜晚，一格格收好", "藏", "夜色值得收藏"),
}

_NEXT_POOL: dict[tuple[str, str], tuple[str, ...]] = {
    ("山", "游"): ("川西环线", "伊犁河谷", "甘南", "青海湖", "阿勒泰", "稻城亚丁"),
    ("山", "栖"): ("莫干山", "腾冲", "雁荡山", "武夷山", "阳朔", "千岛湖"),
    ("城", "游"): ("重庆", "广州", "上海", "成都", "西安", "香港"),
    ("城", "栖"): ("泉州", "苏州", "潮州", "平遥", "扬州", "景德镇"),
}
_CONTINUE_TITLE = {"山": "再往高处走", "城": "再换一座城"}
_CONTRAST_TITLE = {"山": "去山里透口气", "城": "进城补点烟火"}
_SCENE_LABELS = {
    "nature": "山野", "coast": "水岸", "mountain": "高山", "city": "城市",
    "street": "街巷", "culture": "人文", "food": "在地味道", "night": "夜景",
}
_CHART_GROUPS: dict[str, frozenset[str]] = {
    "山海自然": NATURE_TAGS,
    "城市街区": frozenset({"city", "street"}),
    "人文故事": frozenset({"culture"}),
    "在地味道": frozenset({"food"}),
    "夜色光影": frozenset({"night"}),
}
_CN_NUMBERS = "零一二三四五六七八九十"
_BANNED_TERMS = (
    "未知", "未命名", "未定稿", "照片还少", "空白", "占位", "治愈", "松弛感", "氛围感",
    "打卡", "宝藏", "绝绝子", "yyds", "人格测试", "MBTI", "心理", "性格", "搭子",
)
_CONTRAST_PATTERN = re.compile(r"不是.{0,14}而是")
PERSONA_VECTOR_DIMS = (
    "scene_city", "pace_roam", "time_night", "lens_close",
    "nature", "urban", "culture", "food", "night", "water",
    "palette_warmth", "palette_chroma", "palette_lightness",
)


@dataclass(frozen=True)
class ProfileHistory:
    """Compact, non-sensitive accumulation from previously saved reports."""

    previous_report_count: int
    motif_counts: dict[str, int]
    previous_codes: tuple[str, ...] = ()


def build_history_snapshot(
    profile_payloads: list[dict | None],
    *,
    trip_ids: list[str | None] | None = None,
    exclude_trip_id: str | None = None,
) -> ProfileHistory:
    """Collect earlier persona codes and scene motifs, oldest first."""
    motifs: Counter[str] = Counter()
    codes: list[str] = []
    report_count = 0
    seen_trips: set[str] = set()
    for index, payload in enumerate(profile_payloads):
        if not isinstance(payload, dict):
            continue
        trip_id = trip_ids[index] if trip_ids is not None and index < len(trip_ids) else None
        if trip_id and (trip_id == exclude_trip_id or trip_id in seen_trips):
            continue
        if trip_id:
            seen_trips.add(trip_id)
        report_count += 1
        code = str(payload.get("personaCode") or payload.get("persona_code") or "")
        if code in ARCHETYPES:
            codes.append(code)
        signature = payload.get("sceneSignature") or payload.get("scene_signature")
        tokens = signature.get("tokens") if isinstance(signature, dict) else payload.get("keywords")
        if isinstance(tokens, list):
            motifs.update(str(token).strip() for token in set(tokens) if str(token).strip())
    return ProfileHistory(report_count, dict(motifs), tuple(codes))


def build_profile(
    features: JourneyFeatures,
    *,
    requirements: str,
    image_url_by_asset: dict[str, str] | None = None,
    history: ProfileHistory | None = None,
) -> ReportDraftResult:
    """Compute the whole 旅格 with deterministic copy that is already publishable."""
    urls = image_url_by_asset or {}
    history = history or ProfileHistory(0, {})
    axes = _axes(features)
    code = "".join(axis.pole for axis in axes)
    archetype = ARCHETYPES[code]
    stats = _stats(features, urls)
    frame = _signature_frame(features, axes, {stat.asset_id for stat in stats if stat.asset_id}, urls)
    next_stops = _fallback_next_stops(features, axes, archetype, code, requirements)
    tokens = _scene_tokens(features)
    portrait = _fallback_portrait(features)
    journey = dto.JourneyMeta(
        title=_fallback_journey_title(features, tokens),
        destination=features.destination,
        route=features.route[:6],
        spots=features.spots[:6],
        day_count=features.day_count,
        photo_count=features.photo_count,
        city_count=features.stop_count,
        path_km=round(features.path_km) if features.path_km is not None else None,
    )
    evolution_from = history.previous_codes[-1] if history.previous_codes else None
    profile = dto.TravelProfileData(
        archetype_id=archetype.id,
        archetype_name=archetype.name,
        persona_code=code,
        slogan=archetype.tagline,
        summary=portrait,
        spectrums=[],
        keywords=tokens[:3],
        modules=[dto.ProfileModule(title="旅格侧写", content=portrait)],
        next_trip_inspiration=next_stops[0].reason,
        souvenir_line=archetype.word_note,
        visual_theme=_visual_theme(axes, features),
        sample_quality="high" if features.photo_count >= 10 else "medium",
        confidence=round(sum(axis.confidence for axis in axes) / len(axes), 2),
        scope_note="旅格只描述这一程的照片，下一程可能完全不同。",
        scene_signature=dto.SceneSignature(
            title=" · ".join(tokens[:2]),
            tokens=tokens[:4],
            description=portrait,
            evidence_refs=[photo.asset_id for photo in features.photos],
        ),
        next_trip_experiments=[
            dto.NextTripExperiment(
                kind=stop.kind, title=stop.title, reason=stop.reason,
                planning_prompt=stop.planning_prompt,
            )
            for stop in next_stops
        ],
        explicit_requirements=_requirement_clauses(requirements),
        journey_count=history.previous_report_count + 1,
        profile_stage="初见" if not history.previous_report_count else "再次发现",
        returning_motifs=[token for token in tokens if history.motif_counts.get(token)][:3],
        new_facets=[token for token in tokens if not history.motif_counts.get(token)][:3],
        journey=journey,
        axes=axes,
        trip_word=archetype.word,
        trip_word_note=archetype.word_note,
        stats=stats,
        palette=features.palette.colors,
        signature_frame=frame,
        next_stops=next_stops,
        persona_vector=_persona_vector(axes, features),
        evolution_from=evolution_from if evolution_from else None,
    )
    return ReportDraftResult(
        location=features.destination or "未知目的地",
        start_date=features.start_date.isoformat() if features.start_date else None,
        end_date=features.end_date.isoformat() if features.end_date else None,
        personality_summary=archetype.name,
        content=_plain_content(profile),
        chart_data=_chart(features),
        profile_data=profile,
    )


def copy_brief(draft: ReportDraftResult, features: JourneyFeatures) -> dict:
    """Everything the copy editor may rely on — computed facts only."""
    profile = draft.profile_data
    journey = profile.journey
    photos = []
    for photo in features.photos:
        item = {
            "id": photo.asset_id,
            "summary": _clip(photo.analysis.scene_summary, 60),
            "tags": sorted(photo.tags),
        }
        if photo.taken:
            item["time"] = _moment(photo.taken)
        if photo.place_label:
            item["place"] = photo.place_label
        photos.append(item)
    frame = profile.signature_frame
    frame_photo = next((photo for photo in features.photos if frame and photo.asset_id == frame.asset_id), None)
    return {
        "journey": {
            "destination": journey.destination if journey else None,
            "route": journey.route if journey else [],
            "spots": journey.spots if journey else [],
            "days": journey.day_count if journey else None,
            "photo_count": features.photo_count,
            "date_range": [draft.start_date, draft.end_date],
        },
        "persona": {
            "code": profile.persona_code,
            "name": profile.archetype_name,
            "default_tagline": profile.slogan,
            "axes": [
                {
                    "axis": axis.name,
                    "side": axis.right_label if axis.value > 50 else axis.left_label,
                    "lean": _lean_text(axis),
                    "evidence": axis.evidence,
                }
                for axis in profile.axes
            ],
            "previous_code": profile.evolution_from,
        },
        "stats": [
            {"id": stat.id, "label": stat.label, "value": f"{stat.value}{stat.unit}", "fact": stat.caption}
            for stat in profile.stats
        ],
        "signature_frame": {
            "id": frame.asset_id,
            "moment": frame.moment,
            "place": frame.place,
            "summary": frame_photo.analysis.scene_summary if frame_photo else frame.caption,
            "facts": (frame_photo.analysis.observed_facts[:5] if frame_photo else []),
        } if frame else None,
        "palette": [f"{color.name} {color.share}%" for color in profile.palette],
        "visited_places": sorted(features.visited_names()),
        "photos": photos,
    }


def copy_issues(copy: ReportCopyResult, features: JourneyFeatures, stat_ids: set[str]) -> dict[str, str]:
    """Return field → reason for every model field that must not be published."""
    issues: dict[str, str] = {}
    texts = {
        "journey_title": copy.journey_title,
        "tagline": copy.tagline,
        "portrait": copy.portrait,
        "trip_word_note": copy.trip_word_note,
        "moment_line": copy.moment_line,
    }
    for key, text in texts.items():
        problem = _text_problem(text)
        if problem:
            issues[key] = problem
    if not re.fullmatch(r"[\u4e00-\u9fff]", copy.trip_word.strip()):
        issues["trip_word"] = "trip_word 必须恰好是 1 个汉字"
    visited = [name for name in features.visited_names() if len(name) >= 2]
    destinations: list[str] = []
    for key, stop in (("next_continue", copy.next_continue), ("next_contrast", copy.next_contrast)):
        destination = stop.destination.strip()
        problem = _text_problem(stop.title) or _text_problem(stop.reason) or _text_problem(destination)
        if not problem and any(destination in name or name in destination for name in visited):
            problem = f"「{destination}」是这一程已经去过的地方，请换一个新目的地"
        if not problem and destination in destinations:
            problem = "两张锦囊的目的地重复"
        if problem:
            issues[key] = problem
        destinations.append(destination)
    for note in copy.stat_notes:
        if note.id in stat_ids:
            problem = _text_problem(note.caption)
            if problem:
                issues[f"stat:{note.id}"] = problem
    return issues


def apply_creative_copy(
    draft: ReportDraftResult,
    copy: ReportCopyResult,
    rejected: set[str] | frozenset[str] = frozenset(),
) -> ReportDraftResult:
    """Overlay every accepted model field; rejected fields keep computed copy."""
    profile = draft.profile_data

    def accepted(field: str) -> bool:
        return field not in rejected

    update: dict = {}
    if accepted("tagline"):
        update["slogan"] = copy.tagline.strip()
    if accepted("portrait"):
        portrait = copy.portrait.strip()
        update["summary"] = portrait
        update["modules"] = [dto.ProfileModule(title="旅格侧写", content=portrait)]
    if accepted("trip_word") and accepted("trip_word_note"):
        update["trip_word"] = copy.trip_word.strip()
        update["trip_word_note"] = copy.trip_word_note.strip()
        update["souvenir_line"] = copy.trip_word_note.strip()
    if profile.journey and accepted("journey_title"):
        update["journey"] = profile.journey.model_copy(update={"title": copy.journey_title.strip()})
    notes = {note.id: note.caption.strip() for note in copy.stat_notes if accepted(f"stat:{note.id}")}
    if notes:
        update["stats"] = [
            stat.model_copy(update={"caption": notes[stat.id]}) if stat.id in notes else stat
            for stat in profile.stats
        ]
    if profile.signature_frame and accepted("moment_line"):
        update["signature_frame"] = profile.signature_frame.model_copy(update={"caption": copy.moment_line.strip()})
    stops = list(profile.next_stops)
    for index, key, stop_copy in ((0, "next_continue", copy.next_continue), (1, "next_contrast", copy.next_contrast)):
        if index < len(stops) and accepted(key):
            destination = stop_copy.destination.strip()
            stops[index] = stops[index].model_copy(update={
                "title": stop_copy.title.strip(),
                "destination": destination,
                "reason": stop_copy.reason.strip(),
                "planning_prompt": _planning_prompt(destination, profile),
            })
    if stops != list(profile.next_stops):
        update["next_stops"] = stops
        update["next_trip_experiments"] = [
            dto.NextTripExperiment(kind=stop.kind, title=stop.title, reason=stop.reason, planning_prompt=stop.planning_prompt)
            for stop in stops
        ]
        update["next_trip_inspiration"] = stops[0].reason
    updated = profile.model_copy(update=update)
    return draft.model_copy(update={"content": _plain_content(updated), "profile_data": updated})


def signature_asset_id(draft: ReportDraftResult) -> str | None:
    frame = draft.profile_data.signature_frame
    return frame.asset_id if frame else None


# ---------------------------------------------------------------- axes

def _axes(features: JourneyFeatures) -> list[dto.PersonaAxis]:
    return [
        _scene_axis(features),
        _pace_axis(features),
        _time_axis(features),
        _lens_axis(features),
    ]


def _axis(index: int, value: float, *, tie_right: bool, evidence: str, confidence: float) -> dto.PersonaAxis:
    axis_id, name, left_code, right_code, left_word, right_word = AXES[index]
    score = round(max(0.0, min(100.0, value)))
    if score == 50:
        score = 51 if tie_right else 49
    return dto.PersonaAxis(
        id=axis_id, name=name, left_pole=left_word, right_pole=right_word,
        left_label=left_word, right_label=right_word,
        value=score, pole=right_code if score > 50 else left_code,
        evidence=evidence, confidence=round(max(0.0, min(1.0, confidence)), 2),
    )


def _scene_axis(features: JourneyFeatures) -> dto.PersonaAxis:
    nature, urban = features.nature_count, features.urban_count
    total = nature + urban
    value = 50 if not total else 50 + 50 * (urban - nature) / total
    counts = features.scene_counts
    tie_right = counts["culture"] + counts["street"] > counts["mountain"] + counts["coast"]
    return _axis(
        0, value, tie_right=tie_right,
        evidence=f"{nature} 张山野 · {urban} 张城池",
        confidence=total / max(1, features.photo_count),
    )


def _pace_axis(features: JourneyFeatures) -> dto.PersonaAxis:
    days = features.day_count or 1
    stops = max(1, features.stop_count)
    if features.path_km is not None:
        km = features.path_km
        roam = 0.5 * min(1.0, (stops - 1) / 3) + 0.5 * min(1.0, km / days / 150)
        evidence = f"{days} 天 · {stops} 站 · 首尾直线 {km:,.0f} km"
        confidence = features.gps_share
    else:
        roam = 0.5 * min(1.0, (stops - 1) / 3) + 0.25 * min(1.0, (days - 1) / 6)
        evidence = f"{days} 天 · {stops} 个落脚点"
        confidence = 0.35 if features.route else 0.15
    return _axis(1, 100 * roam, tie_right=stops > 1, evidence=evidence, confidence=confidence)


def _time_axis(features: JourneyFeatures) -> dto.PersonaAxis:
    if features.mean_hour_offset is not None and features.earliest and features.latest:
        value = 50 + 50 * max(-1.0, min(1.0, features.mean_hour_offset / 4.5))
        evidence = f"最早 {_clock(features.earliest.taken)} · 最晚 {_clock(features.latest.taken)}"
        return _axis(2, value, tie_right=False, evidence=evidence, confidence=features.time_share)
    night = features.scene_counts["night"]
    value = 50 + 50 * min(1.0, night / max(1.0, 0.4 * features.photo_count)) if night else 35
    return _axis(2, value, tie_right=False, evidence=f"{night} 张夜景", confidence=0.3)


def _lens_axis(features: JourneyFeatures) -> dto.PersonaAxis:
    wide = features.scale_counts["wide"]
    medium = features.scale_counts["medium"]
    close = features.scale_counts["close"]
    denominator = max(1.0, wide + close + 0.5 * medium)
    value = 50 + 50 * (close - wide) / denominator
    return _axis(
        3, value, tie_right=False,
        evidence=f"{wide} 张远景 · {close} 张近物",
        confidence=(wide + close + medium) / max(1, features.photo_count),
    )


def _lean_text(axis: dto.PersonaAxis) -> str:
    strength = abs(axis.value - 50)
    degree = "明显偏向" if strength >= 30 else "偏向" if strength >= 12 else "略偏向"
    label = axis.right_label if axis.value > 50 else axis.left_label
    return f"{degree}{label}"


# ---------------------------------------------------------------- 此行之最 / 高光一帧

def _stats(features: JourneyFeatures, urls: dict[str, str]) -> list[dto.JourneyStat]:
    candidates: list[tuple[float, str, dto.JourneyStat]] = []

    def add(score: float, family: str, stat_id: str, label: str, value: str, unit: str,
            caption: str, photo: JourneyPhoto | None = None) -> None:
        candidates.append((score, family, dto.JourneyStat(
            id=stat_id, label=label, value=value, unit=unit, caption=caption,
            asset_id=photo.asset_id if photo else None,
            image_url=urls.get(photo.asset_id) if photo else None,
        )))

    earliest, latest = features.earliest, features.latest
    if earliest and earliest.taken:
        hour = earliest.taken.hour + earliest.taken.minute / 60
        if hour < 9.5:
            score = 0.98 if hour < 6.5 else 0.9 if hour < 7.5 else 0.7 if hour < 8.5 else 0.45
            add(score, "clock", "earliest", "最早一张", _clock(earliest.taken), "", _photo_caption(earliest), earliest)
    if latest and latest.taken:
        hour = latest.taken.hour + latest.taken.minute / 60
        hour = hour + 24 if hour < 4 else hour
        if hour >= 20.5:
            score = 0.92 if hour >= 23 else 0.8 if hour >= 22 else 0.6
            add(score, "clock", "latest", "最晚一张", _clock(latest.taken), "", _photo_caption(latest), latest)
    if features.max_altitude and features.max_altitude[0] >= 1500:
        height, photo = features.max_altitude
        score = 0.95 if height >= 3000 else 0.8 if height >= 2500 else 0.55
        add(score, "height", "altitude", "最高海拔", f"{height:,.0f}", "m", _photo_caption(photo), photo)
    if features.path_km is not None and features.path_km >= 30:
        km = features.path_km
        score = 0.86 if km >= 600 else 0.72 if km >= 200 else 0.5
        add(score, "space", "path", "首尾直线", f"{km:,.0f}", "km", _span_caption(features))
    if features.stop_count >= 2:
        add(0.72 if features.stop_count >= 3 else 0.5, "space", "stops", "一路途经",
            str(features.stop_count), "站", "→".join(features.route[:5]))
    days = features.day_count
    if days and days >= 2 and features.start_date and features.end_date:
        add(0.4 + min(0.3, days * 0.04), "calendar", "days", "在路上", str(days), "天",
            f"{_md(features.start_date)}—{_md(features.end_date)}")
    if features.busiest_day and features.busiest_day[1] >= 4:
        day, count = features.busiest_day
        add(0.42, "calendar", "busiest", "最满的一天", str(count), "张", f"{_md(day)}按了 {count} 次快门")
    top = next(((tag, count) for tag, count in features.scene_counts.most_common() if tag in _SCENE_LABELS), None)
    if top:
        tag, count = top
        add(0.3, "scene", "scene", "出镜最多", _SCENE_LABELS[tag], "", f"{features.photo_count} 张里有 {count} 张")
    add(0.1, "count", "photos", "这一程", str(features.photo_count), "张", "每一张都参与了计算")

    chosen: list[dto.JourneyStat] = []
    families: set[str] = set()
    ranked = sorted(candidates, key=lambda item: -item[0])
    for strict in (True, False):
        for _score, family, stat in ranked:
            if len(chosen) == 3:
                break
            if stat in chosen or (strict and family in families):
                continue
            chosen.append(stat)
            families.add(family)
    return chosen


def _signature_frame(
    features: JourneyFeatures,
    axes: list[dto.PersonaAxis],
    stat_assets: set[str | None],
    urls: dict[str, str],
) -> dto.SignatureFrame | None:
    if not features.photos:
        return None
    scene, _pace, time_axis, lens = axes
    frequency = features.scene_counts
    total = max(1, features.photo_count)

    def score(photo: JourneyPhoto) -> float:
        quality = (1.0 if photo.analysis.suitability == "good" else 0.65) * (0.6 + 0.4 * photo.analysis.analysis_confidence)
        rarity = (
            sum(1 - frequency[tag] / total for tag in photo.tags) / len(photo.tags)
            if photo.tags else 0.3
        )
        fit = 0.0
        if photo.tags & (NATURE_TAGS if scene.pole == "山" else URBAN_TAGS):
            fit += 0.5
        scale = photo.analysis.shot_scale
        if (lens.pole == "远" and scale == "wide") or (lens.pole == "近" and scale == "close"):
            fit += 0.3
        if photo.taken:
            evening = photo.taken.hour >= 18 or photo.taken.hour < 4
            if (time_axis.pole == "夜") == evening:
                fit += 0.2
        bonus = 0.08 if photo.asset_id in stat_assets else 0.0
        return 0.45 * quality + 0.25 * rarity + 0.3 * fit + bonus

    best = max(features.photos, key=lambda photo: (score(photo), photo.asset_id))
    return dto.SignatureFrame(
        asset_id=best.asset_id,
        image_url=urls.get(best.asset_id),
        caption=_clip(best.analysis.scene_summary, 28),
        place=best.place_label,
        moment=_moment(best.taken) if best.taken else None,
    )


# ---------------------------------------------------------------- deterministic copy

def _fallback_journey_title(features: JourneyFeatures, tokens: list[str]) -> str:
    days = features.day_count
    days_text = _cn_number(days) if days else ""
    if features.destination:
        head = features.destination.split(" · ")[0]
        return f"{head}{days_text}日" if days_text else head
    scene = tokens[0] if tokens else "沿途"
    if days_text:
        return f"{scene}{days_text}日"
    return f"{'与'.join(tokens[:2])}之间" if len(tokens) >= 2 else f"{scene}这一程"


def _fallback_portrait(features: JourneyFeatures) -> str:
    parts: list[str] = []
    days = features.day_count
    if len(features.route) >= 2:
        route = "、".join(features.route[:-1][:3]) + "和" + features.route[-1]
        parts.append(f"{days} 天走过{route}" if days else f"一路走过{route}")
    elif features.destination:
        parts.append(f"{days} 天都留在{features.destination}" if days and days > 1 else f"这一程在{features.destination}")
    nature, urban = features.nature_count, features.urban_count
    if nature and urban and min(nature, urban) / max(nature, urban) >= 0.5:
        parts.append("镜头在山野和城池之间来回切换")
    elif nature >= urban and nature:
        parts.append("镜头大多交给了山野")
    elif urban:
        parts.append("镜头大多留在城里")
    earliest, latest = features.earliest, features.latest
    if earliest and latest and earliest.taken and latest.taken:
        parts.append(f"早到 {_clock(earliest.taken)}，晚到 {_clock(latest.taken)}")
    wide, close = features.scale_counts["wide"], features.scale_counts["close"]
    if wide > close * 2:
        parts.append("远景占了大半")
    elif close > wide:
        parts.append("近处的细节拍得比远景还多")
    text = "，".join(parts) or "这组照片把一程的景色和时间都留了下来"
    return _clip(text + "。", 88)


def _fallback_next_stops(
    features: JourneyFeatures,
    axes: list[dto.PersonaAxis],
    archetype: Archetype,
    code: str,
    requirements: str,
) -> list[dto.NextStop]:
    scene_pole, pace_pole = axes[0].pole, axes[1].pole
    other_scene = "城" if scene_pole == "山" else "山"
    visited = [name for name in features.visited_names() if len(name) >= 2]

    def pick(pool: tuple[str, ...], taken: set[str]) -> str:
        for name in pool:
            if name in taken or name in requirements:
                continue
            if any(name in seen or seen in name for seen in visited):
                continue
            return name
        return pool[-1]

    continue_destination = pick(_NEXT_POOL[(scene_pole, pace_pole)], set())
    contrast_destination = pick(_NEXT_POOL[(other_scene, pace_pole)], {continue_destination})
    profile_hint = f"「{archetype.name}」（{code}）"
    return [
        dto.NextStop(
            kind="continue",
            title=_CONTINUE_TITLE[scene_pole],
            destination=continue_destination,
            reason=f"和这一程同一种{axes[0].left_label if scene_pole == '山' else axes[0].right_label}频率",
            planning_prompt=_prompt_text(continue_destination, profile_hint, axes),
        ),
        dto.NextStop(
            kind="contrast",
            title=_CONTRAST_TITLE[other_scene],
            destination=contrast_destination,
            reason=f"把镜头从{axes[0].left_label if scene_pole == '山' else axes[0].right_label}换到{axes[0].right_label if scene_pole == '山' else axes[0].left_label}",
            planning_prompt=_prompt_text(contrast_destination, profile_hint, axes),
        ),
    ]


def _planning_prompt(destination: str, profile: dto.TravelProfileData) -> str:
    return _prompt_text(destination, f"「{profile.archetype_name}」（{profile.persona_code}）", list(profile.axes))


def _prompt_text(destination: str, profile_hint: str, axes: list[dto.PersonaAxis]) -> str:
    cues = "、".join(
        f"偏爱{axis.right_label if axis.pole == axis.right_pole else axis.left_label}" for axis in axes
    )
    return (
        f"我想去{destination}。我上一程的旅格是{profile_hint}：{cues}。"
        "请先推荐一条适合我的路线方向，等我确认后再细化行程。"
    )


# ---------------------------------------------------------------- helpers

def _persona_vector(axes: list[dto.PersonaAxis], features: JourneyFeatures) -> dto.PersonaVector:
    total = max(1, features.photo_count)
    counts = features.scene_counts
    palette = features.palette
    values = [
        *(axis.value / 100 for axis in axes),
        features.nature_count / total,
        features.urban_count / total,
        counts["culture"] / total,
        counts["food"] / total,
        counts["night"] / total,
        counts["coast"] / total,
        palette.warmth,
        palette.chroma,
        palette.lightness,
    ]
    return dto.PersonaVector(dims=list(PERSONA_VECTOR_DIMS), values=[round(min(1.0, max(0.0, v)), 3) for v in values])


def _visual_theme(axes: list[dto.PersonaAxis], features: JourneyFeatures) -> str:
    scene, _pace, time_axis, _lens = axes
    if features.scene_counts["coast"] >= max(3, features.photo_count // 3):
        return "ocean_blue"
    if scene.pole == "山":
        return "night_purple" if time_axis.pole == "夜" else "forest_light"
    return "city_neon" if time_axis.pole == "夜" else "sunset_orange"


def _scene_tokens(features: JourneyFeatures) -> list[str]:
    tokens = [
        _SCENE_LABELS[tag]
        for tag, count in features.scene_counts.most_common()
        if count and tag in _SCENE_LABELS
    ]
    return list(dict.fromkeys(tokens))[:4] or ["山野"]


def _chart(features: JourneyFeatures) -> list[dto.ReportChartPoint]:
    total = max(1, features.photo_count)
    return [
        dto.ReportChartPoint(
            dimension=label,
            value=round(100 * sum(bool(photo.tags & tags) for photo in features.photos) / total),
        )
        for label, tags in _CHART_GROUPS.items()
    ]


def _plain_content(profile: dto.TravelProfileData) -> str:
    journey = profile.journey
    lines = [f"旅格｜{profile.archetype_name}（{profile.persona_code}）", profile.slogan]
    if journey:
        route = " → ".join(journey.route)
        lines.append(f"{journey.title}{'｜' + route if route else ''}")
    if profile.summary:
        lines.append(profile.summary)
    if profile.trip_word:
        lines.append(f"本程一字｜{profile.trip_word}：{profile.trip_word_note or ''}")
    for stat in profile.stats:
        lines.append(f"{stat.label}｜{stat.value}{stat.unit} {stat.caption}".strip())
    for stop in profile.next_stops:
        lines.append(f"下一站｜{stop.destination}：{stop.reason}")
    return "\n".join(line for line in lines if line)


def _requirement_clauses(requirements: str) -> list[str]:
    clauses = [clause.strip() for clause in re.split(r"[\n，。；;]+", requirements) if clause.strip()]
    return list(dict.fromkeys(clause[:80] for clause in clauses))[:4]


def _text_problem(text: str) -> str | None:
    value = text.strip()
    if not value:
        return "内容为空"
    for term in _BANNED_TERMS:
        if term.lower() in value.lower():
            return f"含有不允许的表达「{term}」"
    if _CONTRAST_PATTERN.search(value):
        return "不要使用“不是……而是……”句式"
    return None


def _photo_caption(photo: JourneyPhoto) -> str:
    parts = []
    if photo.taken:
        parts.append(_md(photo.taken.date()))
    if photo.place_label:
        parts.append(photo.place_label)
    return " · ".join(parts) or _clip(photo.analysis.scene_summary, 16)


def _span_caption(features: JourneyFeatures) -> str:
    span = features.span
    if span is None:
        return "最早一张到最晚一张的直线"
    start, end = span
    origin = start.city or start.place_label
    destination = end.city or end.place_label
    if origin and destination and origin != destination:
        return f"{origin}到{destination}的直线"
    if start.taken and end.taken:
        return f"{_md(start.taken.date())}到{_md(end.taken.date())}的直线"
    return "最早一张到最晚一张的直线"


def _clock(value: datetime | None) -> str:
    return value.strftime("%H:%M") if value else ""


def _md(value: date) -> str:
    return f"{value.month}月{value.day}日"


def _moment(value: datetime) -> str:
    return f"{_md(value.date())} {_clock(value)}"


def _cn_number(value: int) -> str:
    if 0 < value <= 10:
        return _CN_NUMBERS[value]
    if 10 < value < 20:
        return "十" + _CN_NUMBERS[value - 10]
    return str(value)


def _clip(text: str, limit: int) -> str:
    cleaned = re.sub(r"\s+", "", (text or "").strip())
    if len(cleaned) <= limit:
        return cleaned
    candidate = cleaned[:limit]
    for marks in ("。！？；", "，、："):
        cut = max(candidate.rfind(mark) for mark in marks)
        if cut >= limit // 2:
            return candidate[:cut].rstrip("，、：；") + "。"
    return candidate[: limit - 1] + "…"
