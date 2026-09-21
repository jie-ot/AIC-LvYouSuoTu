"""Concrete, user-controlled travel memory."""

from __future__ import annotations

import hashlib
import hmac
import re
from copy import deepcopy
from typing import Any

from sqlalchemy import update
from sqlmodel import Session, select

from app.core.config import settings
from app.core.exceptions import InvalidParamError
from app.models.base import utcnow
from app.models.user_memory import UserMemory
from app.models.user_memory_event import UserMemoryEvent
from app.services import id_service

INITIAL_MEMORY_TEXT = "暂无旅行记忆。"
VALID_SOURCE_TYPES = {"generate", "manual", "explicit_requirement"}
PLANNING_PREFERENCE_ORDER = (
    ("transport", "交通"), ("hotel", "住宿"),
    ("attractions", "想去的地方"), ("food", "餐饮"),
    ("pace", "行程节奏"), ("other", "其他"),
)
TAXONOMY = (
    ("pace.relaxed", "pace", ("慢", "不赶", "留白", "弹性", "轻松"), "偏好留有缓冲的慢节奏行程"),
    ("culture.local", "attractions", ("历史", "文化", "博物馆", "老城", "街区", "建筑"), "偏好有历史和地方故事的旅行场景"),
    ("nature.open", "attractions", ("自然景观", "山野", "海边", "海岸", "湖畔", "森林", "日落"), "偏好自然景观与开阔空间"),
    ("food.local", "food", ("美食", "小吃", "咖啡", "市集", "本地菜"), "重视在地饮食和街区生活体验"),
    ("record.visual", "other", ("摄影", "拍照", "画面", "光影", "记录"), "偏好用照片记录旅行中的光线与空间"),
    ("planning.structured", "pace", ("详细计划", "提前预订", "明确时间"), "偏好提前确认关键安排"),
)

CATEGORY_LABELS = {
    "transport": "交通",
    "hotel": "住宿",
    "pace": "行程节奏",
    "food": "餐饮",
    "accessibility": "同行与无障碍",
    "budget": "预算",
    "attractions": "想去的地方",
    "other": "其他",
}

CATEGORY_KEYWORDS = {
    "transport": ("高铁", "动车", "火车", "飞机", "自驾", "地铁", "公交", "换乘", "打车", "交通", "充电桩"),
    "hotel": ("酒店", "住宿", "民宿", "房间", "地铁站", "隔音", "安静", "入住", "只住", "早餐"),
    "pace": ("每天", "景点", "午休", "休息", "节奏", "不赶", "宽松", "早起", "晚起", "留白"),
    "food": ("不吃", "忌口", "过敏", "素食", "清真", "吃辣", "不辣", "餐厅", "饮食"),
    "accessibility": ("台阶", "爬坡", "轮椅", "无障碍", "老人", "长辈", "父母", "孩子", "儿童", "婴儿", "少走", "步行", "宠物", "带狗", "带猫"),
    "budget": ("预算", "每晚", "人均", "花费", "费用", "省钱"),
    "attractions": (
        "博物馆", "展览", "徒步", "公园", "古镇", "海边", "演出", "亲子",
        "自然景观", "山野", "湖畔", "森林", "峡谷", "古迹", "街区", "历史", "网红店",
    ),
}

CREATIVE_ONLY_TERMS = (
    "明信片", "排版", "字体", "色调", "滤镜", "横版", "竖版", "裁图", "裁剪",
    "水印", "封面", "图片风格", "照片风格",
)
ABSTRACT_MEMORY_TERMS = (
    "旅行人格", "人格", "画像", "喜欢光影", "空间感", "氛围感", "松弛感",
    "诗意", "治愈", "小确幸", "有温度", "审美", "质感",
)
REQUIREMENT_MARKERS = (
    "要", "不要", "只", "必须", "需要", "优先", "避免", "希望", "想去", "不去",
    "不能", "不想", "不吃", "带狗", "带猫", "同行", "靠近", "以内", "最多", "至少",
)


def memory_category(text: str, fallback: str = "other") -> str:
    value = " ".join(text.strip().split())
    for category, words in CATEGORY_KEYWORDS.items():
        if any(word in value for word in words):
            return category
    return fallback if fallback in CATEGORY_LABELS else "other"


def is_actionable_requirement(text: str) -> bool:
    value = " ".join(text.strip().split())
    if len(value) < 2 or len(value) > 240:
        return False
    if any(term in value for term in ABSTRACT_MEMORY_TERMS):
        return False
    category = memory_category(value)
    if category != "other":
        return True
    if any(term in value for term in CREATIVE_ONLY_TERMS):
        return False
    return any(marker in value for marker in REQUIREMENT_MARKERS)


def _memory_item_id(text: str) -> str:
    normalized = " ".join(text.strip().lower().split())
    return f"memory_{hashlib.sha256(normalized.encode('utf-8')).hexdigest()[:12]}"


def _upgrade_to_v3(memory: UserMemory) -> dict:
    raw = deepcopy(memory.memory_json or {})
    if raw.get("schema_version") == 3 and isinstance(raw.get("items"), list):
        return raw

    now = utcnow().isoformat()
    items: list[dict] = []
    legacy_items: list[dict] = []
    seen: set[str] = set()
    planning = raw.get("planning_preferences")
    if isinstance(planning, dict):
        for category, _label in PLANNING_PREFERENCE_ORDER:
            text = " ".join(str(planning.get(category) or "").strip().split())
            if not text:
                continue
            if category == "other" and not is_actionable_requirement(text):
                legacy_items.append({"text": text, "archived_at": now})
                continue
            item_id = _memory_item_id(text)
            if item_id in seen:
                continue
            seen.add(item_id)
            items.append({
                "id": item_id,
                "text": text,
                "category": memory_category(text, category),
                "state": "saved",
                "enabled": True,
                "source_kind": "manual",
                "source_trip_id": None,
                "source_trip_title": None,
                "created_at": now,
                "updated_at": now,
            })

    for pref in raw.get("preferences", []) if isinstance(raw.get("preferences"), list) else []:
        if not isinstance(pref, dict):
            continue
        text = " ".join(str(pref.get("summary") or "").strip().split())
        if not text:
            continue
        if (
            pref.get("origin") == "manual"
            and pref.get("state") == "active"
            and is_actionable_requirement(text)
        ):
            item_id = _memory_item_id(text)
            if item_id not in seen:
                seen.add(item_id)
                items.append({
                    "id": item_id,
                    "text": text,
                    "category": memory_category(text, str(pref.get("category") or "other")),
                    "state": "saved",
                    "enabled": True,
                    "source_kind": "manual",
                    "source_trip_id": None,
                    "source_trip_title": None,
                    "created_at": str(pref.get("last_seen") or now),
                    "updated_at": str(pref.get("last_seen") or now),
                })
        else:
            legacy_items.append({"text": text, "archived_at": now})

    upgraded = {
        **raw,
        "schema_version": 3,
        "enabled": bool(raw.get("enabled", True)),
        "items": items,
        "legacy_items": legacy_items,
    }
    memory.memory_json = upgraded
    memory.memory_text = _render_v3_memory_text(upgraded)
    return upgraded


def _render_v3_memory_text(mem_json: dict) -> str:
    if not mem_json.get("enabled", True):
        return ""
    lines = [
        f"- {str(item.get('text') or '').strip()}"
        for item in mem_json.get("items", [])
        if isinstance(item, dict)
        and item.get("state") == "saved"
        and item.get("enabled", True)
        and str(item.get("text") or "").strip()
    ]
    return "\n".join(lines)


def _looks_corrupt(value: object) -> bool:
    text = str(value or "")
    return "\ufffd" in text or any(ord(char) < 32 and char not in "\n\t" for char in text)


def get_or_create_current_memory(session: Session, user_id: str) -> UserMemory:
    memory = session.exec(select(UserMemory).where(UserMemory.user_id == user_id)).first()
    if memory is not None:
        _upgrade_to_v3(memory)
        session.add(memory)
        return memory
    memory = UserMemory(
        id=id_service.new_memory_id(), user_id=user_id, memory_text=INITIAL_MEMORY_TEXT,
        memory_json={"schema_version": 3, "enabled": True, "items": [], "legacy_items": []}, version=1,
    )
    session.add(memory)
    session.flush()
    return memory


NEGATIVE_SIGNAL = (
    r"(?:不(?:太|怎么)?喜欢|不爱|讨厌|不想去|不想看|不想吃|不想要|不希望|"
    r"不要|不是|不去|不看|不吃|别选|别用|别去|别看|别吃|避开|排除|拒绝|禁止)"
)
PREFERENCE_CLAUSE_BOUNDARY = re.compile(
    r"(?:[\n，。；;]+|但是|不过|然而|反而|而是|但|却)"
)


def preference_clauses(raw: str) -> list[str]:
    """Split contrastive wishes before deciding polarity.

    A bounded cross-sentence regex turns ``不喜欢博物馆但是喜欢自然`` into
    two negative preferences.  Treating contrast words as clause boundaries
    keeps the explicit positive half positive while preserving coordinated
    negatives such as ``不喜欢博物馆和历史街区``.
    """
    value = " ".join(raw.strip().split())
    return [part.strip() for part in PREFERENCE_CLAUSE_BOUNDARY.split(value) if part.strip()]


def preference_term_polarity(raw: str, word: str) -> int:
    """Return the last explicit polarity for ``word``: -1, 0, or +1."""
    polarity = 0
    for clause in preference_clauses(raw):
        for match in re.finditer(re.escape(word), clause):
            prefix = clause[:match.start()]
            polarity = -1 if re.search(NEGATIVE_SIGNAL, prefix) else 1
    return polarity


def _term_is_negated(value: str, word: str) -> bool:
    return preference_term_polarity(value, word) < 0


def negated_taxonomy_keys(raw: str) -> set[str]:
    value = " ".join(raw.strip().split())
    blocked = {
        canonical_key
        for canonical_key, _category, words, _summary in TAXONOMY
        if any(_term_is_negated(value, word) for word in words)
    }
    if re.search(r"(?:不吃|忌口|过敏)", value):
        blocked.add("food.local")
    return blocked


def canonicalize(raw: str, *, reject_negated: bool = False) -> tuple[str, str, str] | None:
    value = " ".join(raw.strip().split())
    if len(value) < 6 or len(value) > 180:
        return None
    negated_keys = negated_taxonomy_keys(value)
    for canonical_key, category, words, summary in TAXONOMY:
        if any(word in value for word in words):
            if canonical_key in negated_keys:
                if reject_negated:
                    return None
                digest = hashlib.sha256(value.lower().encode("utf-8")).hexdigest()[:16]
                return f"manual.{digest}", "other", value
            return canonical_key, category, summary
    digest = hashlib.sha256(value.lower().encode("utf-8")).hexdigest()[:16]
    return f"manual.{digest}", "other", value


def _tombstone(canonical_key: str) -> str:
    return hmac.new(
        settings.MEMORY_TOMBSTONE_SECRET.encode("utf-8"),
        canonical_key.encode("utf-8"), hashlib.sha256,
    ).hexdigest()


def stable_preference_id(pref: dict) -> str:
    existing = str(pref.get("preference_id") or "").strip()
    if existing:
        return existing
    raw_key = str(pref.get("canonical_key") or pref.get("key") or pref.get("summary") or "")
    return f"pref_{hashlib.sha256(raw_key.encode()).hexdigest()[:12]}"


def _upgrade_pref(pref: dict) -> dict:
    item = deepcopy(pref)
    raw_key = str(item.get("canonical_key") or item.get("key") or item.get("summary") or "")
    item["preference_id"] = stable_preference_id(item)
    item["canonical_key"] = raw_key
    item["origin"] = "manual" if item.get("source_type") == "manual" else str(item.get("origin") or "inferred")
    legacy_state = item.get("state") or item.get("status")
    item["state"] = legacy_state if legacy_state in {"candidate", "active", "dismissed"} else "candidate"
    item.pop("status", None)
    evidences = item.get("evidences")
    if not isinstance(evidences, list):
        evidences = []
        refs = item.get("source_refs", []) if isinstance(item.get("source_refs"), list) else []
        for ref in refs:
            evidences.append({"operation_id": str(ref), "trip_fingerprint": str(ref)})
    item["evidences"] = evidences
    item["source_refs"] = [str(ref) for ref in item.get("source_refs", []) if ref]
    independent = {(e.get("operation_id"), e.get("trip_fingerprint")) for e in evidences if isinstance(e, dict)}
    trips = {trip for _, trip in independent if trip}
    if item["origin"] != "manual" and item["state"] == "active" and not (len(independent) >= 2 and len(trips) >= 2):
        item["state"] = "candidate"
    return item


def _render_planning_preferences(planning: dict | None) -> list[str]:
    if not isinstance(planning, dict):
        return []
    lines = [f"- {label}：{str(planning.get(key) or '').strip()}" for key, label in PLANNING_PREFERENCE_ORDER if str(planning.get(key) or "").strip()]
    return (["用户主动确认的硬约束（优先遵守）：", *lines] if lines else [])


def _render_memory_text(preferences: list[dict], planning_preferences: dict | None = None) -> str:
    lines = _render_planning_preferences(planning_preferences)
    active: list[dict] = []
    for pref in preferences:
        if isinstance(pref, dict):
            upgraded = _upgrade_pref(pref)
            if (
                upgraded.get("state") == "active"
                and not _looks_corrupt(upgraded.get("summary"))
            ):
                active.append(upgraded)
    if active:
        if lines:
            lines.append("")
        lines.append("已保存的旅行记忆：")
    lines.extend(
        f"- {pref.get('summary', '')}"
        for pref in active
        if str(pref.get("summary") or "").strip()
    )
    return "\n".join(lines) if lines else INITIAL_MEMORY_TEXT


def build_memory_summary(memory: UserMemory, max_chars: int = 1000) -> str:
    mem_json = memory.memory_json or {}
    if mem_json.get("schema_version") == 3:
        return _render_v3_memory_text(mem_json)[:max_chars]
    manual_lines = _render_planning_preferences(
        mem_json.get("planning_preferences") if isinstance(mem_json.get("planning_preferences"), dict) else None
    )
    text = _render_memory_text(
        list(mem_json.get("preferences", [])) if isinstance(mem_json.get("preferences"), list) else [],
        mem_json.get("planning_preferences") if isinstance(mem_json.get("planning_preferences"), dict) else None,
    )
    chosen: list[str] = list(manual_lines)
    used = sum(len(line) + 1 for line in chosen)
    for line in text.splitlines():
        if line in manual_lines or (manual_lines and line == ""):
            continue
        addition = len(line) + (1 if chosen else 0)
        if used + addition > max_chars:
            break
        chosen.append(line)
        used += addition
    return "\n".join(chosen) or INITIAL_MEMORY_TEXT


def merge_memory_update(
    session: Session, *, user_id: str, add_preferences: list[str],
    weaken_preferences: list[str], evidence_summary: str, confidence: float,
    source_type: str, source_id: str | None, trip_fingerprint: str | None = None,
    expected_version: int | None = None,
) -> UserMemory:
    """Merge at most one evidence per canonical key and operation."""
    del weaken_preferences, evidence_summary
    if source_type not in VALID_SOURCE_TYPES:
        raise ValueError(f"invalid source_type: {source_type}")
    if source_type == "generate" and (not source_id or not trip_fingerprint):
        raise ValueError("automatic memory evidence requires operation and trip fingerprint")
    memory = get_or_create_current_memory(session, user_id)
    if expected_version is not None and memory.version != expected_version:
        raise InvalidParamError("旅行记忆已在其他页面更新，请刷新后重试")
    # Legacy callers used `generate` for photo-derived guesses. Keep the input
    # compatible, but never persist those guesses as travel memory.
    if source_type == "generate":
        return memory
    if source_id and session.exec(
        select(UserMemoryEvent).where(
            UserMemoryEvent.memory_id == memory.id,
            UserMemoryEvent.source_type == source_type,
            UserMemoryEvent.source_id == source_id,
        )
    ).first() is not None:
        return memory

    if source_type == "explicit_requirement":
        mem_json = _upgrade_to_v3(memory)
        items = [deepcopy(item) for item in mem_json.get("items", []) if isinstance(item, dict)]
        existing_texts = {
            " ".join(str(item.get("text") or "").strip().lower().split())
            for item in items
        }
        now = utcnow().isoformat()
        changed: list[str] = []
        for raw in add_preferences:
            text = " ".join(raw.strip().split())
            normalized = text.lower()
            if not is_actionable_requirement(text) or normalized in existing_texts:
                continue
            item_id = _memory_item_id(text)
            items.append({
                "id": item_id,
                "text": text,
                "category": memory_category(text),
                "state": "suggested",
                "enabled": False,
                "source_kind": "explicit_requirement",
                "source_trip_id": trip_fingerprint,
                "source_trip_title": None,
                "created_at": now,
                "updated_at": now,
            })
            existing_texts.add(normalized)
            changed.append(item_id)
        if not changed:
            return memory
        mem_json.update(schema_version=3, items=items)
        return _cas_write(
            session,
            memory,
            mem_json=mem_json,
            source_type=source_type,
            source_id=source_id or f"explicit:{memory.version + 1}",
            trip_id=trip_fingerprint,
            delta={"item_ids": changed, "kind": "suggestion"},
            expected_version=memory.version,
        )

    mem_json = deepcopy(memory.memory_json or {})
    preferences = [_upgrade_pref(p) for p in mem_json.get("preferences", []) if isinstance(p, dict)]
    by_key = {p.get("canonical_key"): p for p in preferences}
    tombstones = set(str(v) for v in mem_json.get("tombstones", []) if v)
    changed: list[str] = []
    now = utcnow().isoformat()
    operation_id = source_id or f"manual:{memory.version + 1}"
    fingerprint = trip_fingerprint or operation_id
    seen_keys: set[str] = set()
    for raw in add_preferences:
        canon = canonicalize(raw, reject_negated=source_type != "manual")
        if canon is None:
            continue
        canonical_key, category, summary = canon
        if source_type != "manual" and canonical_key.startswith("manual."):
            continue
        if canonical_key in seen_keys or _tombstone(canonical_key) in tombstones:
            continue
        seen_keys.add(canonical_key)
        pref = by_key.get(canonical_key)
        if pref is None:
            pref = {
                "preference_id": f"pref_{hashlib.sha256(canonical_key.encode()).hexdigest()[:12]}",
                "canonical_key": canonical_key, "category": category, "summary": summary,
                "origin": "manual" if source_type == "manual" else "inferred",
                "state": "active" if source_type == "manual" else "candidate",
                "confidence": 1.0 if source_type == "manual" else min(0.49, max(0.1, float(confidence))),
                "evidences": [], "source_refs": [], "last_seen": now,
            }
            preferences.append(pref)
            by_key[canonical_key] = pref
        evidences = list(pref.get("evidences", []))
        if not any(e.get("operation_id") == operation_id for e in evidences if isinstance(e, dict)):
            evidences.append({"operation_id": operation_id, "trip_fingerprint": fingerprint})
        pref["evidences"] = evidences
        pref["source_refs"] = list(dict.fromkeys([*pref.get("source_refs", []), operation_id]))
        pref["last_seen"] = now
        if source_type == "manual":
            pref.update(origin="manual", state="active", confidence=1.0, summary=summary)
        else:
            independent = {(e.get("operation_id"), e.get("trip_fingerprint")) for e in evidences if isinstance(e, dict)}
            trips = {trip for _, trip in independent if trip}
            if len(independent) >= 2 and len(trips) >= 2:
                pref["state"] = "active"
                pref["confidence"] = min(0.9, 0.45 + 0.15 * len(independent))
            else:
                pref["state"] = "candidate"
        changed.append(pref["preference_id"])

    if not changed:
        return memory
    mem_json.update(schema_version=2, preferences=preferences, tombstones=sorted(tombstones))
    return _cas_write(
        session, memory, mem_json=mem_json, source_type=source_type,
        source_id=operation_id, delta={"preference_ids": changed, "kind": "manual" if source_type == "manual" else "observation"},
        expected_version=memory.version,
    )


def update_preference(
    session: Session, *, user_id: str, preference_id: str, title: str, content: str,
    expected_version: int | None,
) -> UserMemory:
    memory = get_or_create_current_memory(session, user_id)
    _check_version(memory, expected_version)
    upgraded = _upgrade_to_v3(memory)
    if any(str(item.get("id")) == preference_id for item in upgraded.get("items", []) if isinstance(item, dict)):
        return patch_memory_item(
            session,
            user_id=user_id,
            item_id=preference_id,
            text=content.strip() or title.strip(),
            confirm=True,
            expected_version=memory.version,
        )
    mem_json = deepcopy(memory.memory_json or {})
    prefs = [_upgrade_pref(p) for p in mem_json.get("preferences", []) if isinstance(p, dict)]
    target = next((p for p in prefs if p.get("preference_id") == preference_id), None)
    if target is None:
        raise InvalidParamError("该记忆不存在或已被删除")
    canon = canonicalize(f"{title.strip()}\n{content.strip()}")
    if canon is None:
        raise InvalidParamError("记忆内容不合法")
    canonical_key, category, _summary = canon
    display_summary = (
        content.strip()
        if title.strip() == "待确认观察"
        else f"{title.strip()}\n{content.strip()}"
    )
    desired = {
        "canonical_key": canonical_key,
        "category": category,
        "summary": display_summary,
        "origin": "manual",
        "state": "active",
        "confidence": 1.0,
    }
    if all(target.get(key) == value for key, value in desired.items()):
        return memory
    old_canonical_key = str(target.get("canonical_key") or "")
    if old_canonical_key and canonical_key != old_canonical_key:
        mem_json["tombstones"] = sorted(
            set(str(value) for value in mem_json.get("tombstones", []) if value)
            | {_tombstone(old_canonical_key)}
        )
    target.update(**desired, last_seen=utcnow().isoformat())
    mem_json.update(schema_version=2, preferences=prefs)
    return _cas_write(session, memory, mem_json=mem_json, source_type="manual", source_id=f"edit:{preference_id}:{memory.version}", delta={"preference_id": preference_id, "kind": "edit"}, expected_version=memory.version)


def forget_preference(
    session: Session, *, user_id: str, preference_id: str, expected_version: int | None = None,
) -> UserMemory:
    memory = get_or_create_current_memory(session, user_id)
    _check_version(memory, expected_version)
    upgraded = _upgrade_to_v3(memory)
    if any(str(item.get("id")) == preference_id for item in upgraded.get("items", []) if isinstance(item, dict)):
        return delete_memory_item(
            session,
            user_id=user_id,
            item_id=preference_id,
            expected_version=memory.version,
        )
    mem_json = deepcopy(memory.memory_json or {})
    prefs = [_upgrade_pref(p) for p in mem_json.get("preferences", []) if isinstance(p, dict)]
    target = next((p for p in prefs if p.get("preference_id") == preference_id), None)
    if target is None:
        raise InvalidParamError("该记忆不存在或已被删除")
    forgotten_keys = {str(target.get("canonical_key") or "").strip()}
    normalized = canonicalize(str(target.get("summary") or ""))
    if normalized is not None:
        forgotten_keys.add(normalized[0])
    tombstones = {
        _tombstone(canonical_key)
        for canonical_key in forgotten_keys
        if canonical_key
    }
    mem_json["schema_version"] = 2
    mem_json["preferences"] = [p for p in prefs if p.get("preference_id") != preference_id]
    mem_json["tombstones"] = sorted(set(mem_json.get("tombstones", [])) | tombstones)
    for event in session.exec(select(UserMemoryEvent).where(UserMemoryEvent.memory_id == memory.id)).all():
        payload = event.delta_json or {}
        if preference_id in str(payload) or str(target.get("summary") or "") in str(payload):
            event.delta_json = {"redacted": True, "tombstones": sorted(tombstones)}
            session.add(event)
    return _cas_write(
        session,
        memory,
        mem_json=mem_json,
        source_type="manual",
        source_id=f"forget:{preference_id}:{memory.version}",
        delta={"kind": "forget", "tombstones": sorted(tombstones)},
        expected_version=memory.version,
    )


def update_manual_fields(
    session: Session, *, user_id: str, key: str, value: dict,
    expected_version: int | None,
) -> UserMemory:
    memory = get_or_create_current_memory(session, user_id)
    _check_version(memory, expected_version)
    mem_json = deepcopy(memory.memory_json or {})
    if mem_json.get(key) == value and mem_json.get("schema_version") == 2:
        return memory
    mem_json["schema_version"] = 2
    mem_json[key] = value
    return _cas_write(session, memory, mem_json=mem_json, source_type="manual", source_id=f"{key}:{memory.version}", delta={"kind": key}, expected_version=memory.version)


def add_memory_item(
    session: Session,
    *,
    user_id: str,
    text: str,
    category: str = "other",
    expected_version: int | None = None,
) -> UserMemory:
    memory = get_or_create_current_memory(session, user_id)
    _check_version(memory, expected_version)
    mem_json = _upgrade_to_v3(memory)
    clean = " ".join(text.strip().split())
    if len(clean) < 2:
        raise InvalidParamError("旅行记忆不能为空")
    items = [deepcopy(item) for item in mem_json.get("items", []) if isinstance(item, dict)]
    normalized = clean.lower()
    if any(" ".join(str(item.get("text") or "").strip().lower().split()) == normalized for item in items):
        return memory
    now = utcnow().isoformat()
    item_id = _memory_item_id(clean)
    items.append({
        "id": item_id,
        "text": clean,
        "category": category if category in CATEGORY_LABELS else memory_category(clean),
        "state": "saved",
        "enabled": True,
        "source_kind": "manual",
        "source_trip_id": None,
        "source_trip_title": None,
        "created_at": now,
        "updated_at": now,
    })
    mem_json.update(schema_version=3, items=items)
    return _cas_write(
        session,
        memory,
        mem_json=mem_json,
        source_type="manual",
        source_id=f"add:{item_id}:{memory.version}",
        delta={"item_id": item_id, "kind": "add"},
        expected_version=memory.version,
    )


def record_trip_observation(
    session: Session,
    *,
    user_id: str,
    trip_id: str,
    operation_id: str,
    analysis: Any,
    photos: list[Any],
) -> UserMemory:
    """Store one replaceable photo-analysis snapshot for a trip.

    This is evidence, not a preference: it never enters the planning context by
    itself. Re-running the same generation operation is idempotent, while a new
    operation for the same trip replaces the old snapshot instead of inflating
    support counts.
    """
    memory = get_or_create_current_memory(session, user_id)
    if session.exec(
        select(UserMemoryEvent).where(
            UserMemoryEvent.memory_id == memory.id,
            UserMemoryEvent.source_type == "trip_observation",
            UserMemoryEvent.source_id == operation_id,
        )
    ).first() is not None:
        return memory

    photo_input = {
        str(getattr(photo, "asset_id", "")): photo
        for photo in photos
        if getattr(photo, "asset_id", None)
    }
    dates: set[str] = set()
    locations: set[str] = set()
    location_labels: set[str] = set()
    hours: set[int] = set()
    capture_minutes_by_date: dict[str, list[int]] = {}
    scene_tags: set[str] = set()
    observed_facts: list[str] = []
    useful_count = 0
    for item in getattr(analysis, "photos", []):
        if getattr(item, "suitability", "usable") == "unsuitable":
            continue
        useful_count += 1
        source = photo_input.get(str(getattr(item, "asset_id", "")))
        taken_at = str(getattr(source, "taken_at", "") or "").strip()
        guessed_date = str(getattr(item, "taken_date_guess", "") or "").strip()
        if taken_at:
            dates.add(taken_at[:10])
            time_match = re.search(r"(?:T|\s)(\d{1,2}):(\d{2})", taken_at)
            if time_match:
                hour = int(time_match.group(1))
                minute = int(time_match.group(2))
                hours.add(hour)
                capture_minutes_by_date.setdefault(taken_at[:10], []).append(hour * 60 + minute)
        elif guessed_date:
            dates.add(guessed_date[:10])
        input_location = str(getattr(source, "location", "") or "").strip()
        guessed_location = str(getattr(item, "location_guess", "") or "").strip()
        if input_location:
            locations.add(input_location)
        if guessed_location and guessed_location not in {"未知地点", "未知目的地"}:
            locations.add(guessed_location)
            location_labels.add(guessed_location)
        scene_tags.update(str(tag) for tag in getattr(item, "scene_tags", []) if tag)
        for fact in getattr(item, "observed_facts", []):
            clean = " ".join(str(fact or "").strip().split())
            if clean and clean not in observed_facts:
                observed_facts.append(clean)

    mem_json = _upgrade_to_v3(memory)
    observations = deepcopy(mem_json.get("trip_observations", {}))
    if not isinstance(observations, dict):
        observations = {}
    daily_spans = [
        max(values) - min(values)
        for values in capture_minutes_by_date.values()
        if len(values) >= 2
    ]
    longest_same_day_span = max(daily_spans, default=0) / 60
    snapshot = {
        "trip_id": trip_id,
        "operation_id": operation_id,
        "photo_count": useful_count,
        "photo_dates": sorted(value for value in dates if value),
        "photo_day_count": len({value[:10] for value in dates if value}),
        "photo_locations": sorted(locations)[:8],
        "photo_location_count": len(locations),
        "photo_location_labels": sorted(location_labels)[:8],
        "capture_hours": sorted(hours),
        "longest_same_day_span_hours": round(longest_same_day_span, 1),
        "scene_tags": sorted(scene_tags),
        "observed_facts": observed_facts[:8],
        "updated_at": utcnow().isoformat(),
    }
    observations[trip_id] = snapshot
    mem_json.update(schema_version=3, trip_observations=observations)
    return _cas_write(
        session,
        memory,
        mem_json=mem_json,
        source_type="trip_observation",
        source_id=operation_id,
        trip_id=trip_id,
        delta={
            "kind": "photo_observation",
            "trip_id": trip_id,
            "photo_count": useful_count,
            "photo_day_count": snapshot["photo_day_count"],
            "scene_tags": snapshot["scene_tags"],
        },
        expected_version=memory.version,
    )


def confirm_observed_pattern(
    session: Session,
    *,
    user_id: str,
    pattern: Any,
    expected_version: int | None = None,
) -> UserMemory:
    """Turn an explainable cross-trip observation into a planning rule."""
    memory = get_or_create_current_memory(session, user_id)
    _check_version(memory, expected_version)
    pattern_id = str(getattr(pattern, "id", "") or "").strip()
    planning_text = " ".join(str(getattr(pattern, "planning_text", "") or "").strip().split())
    if not pattern_id or not planning_text or not bool(getattr(pattern, "confirmable", False)):
        raise InvalidParamError("这条观察还需要更多旅行记录")
    mem_json = _upgrade_to_v3(memory)
    items = [deepcopy(item) for item in mem_json.get("items", []) if isinstance(item, dict)]
    if any(str(item.get("source_pattern_id") or "") == pattern_id for item in items):
        return memory
    now = utcnow().isoformat()
    item_id = _memory_item_id(planning_text)
    items.append({
        "id": item_id,
        "text": planning_text,
        "category": str(getattr(pattern, "category", "other") or "other"),
        "state": "saved",
        "enabled": True,
        "source_kind": "observed_pattern",
        "source_pattern_id": pattern_id,
        "source_trip_ids": list(getattr(pattern, "source_trip_ids", []) or []),
        "source_trip_id": None,
        "source_trip_title": None,
        "created_at": now,
        "updated_at": now,
    })
    mem_json.update(schema_version=3, items=items)
    return _cas_write(
        session,
        memory,
        mem_json=mem_json,
        source_type="manual",
        source_id=f"confirm:{pattern_id}:{memory.version + 1}",
        trip_id=None,
        delta={"kind": "confirmed_pattern", "pattern_id": pattern_id, "item_id": item_id},
        expected_version=memory.version,
    )


def patch_memory_item(
    session: Session,
    *,
    user_id: str,
    item_id: str,
    text: str | None = None,
    category: str | None = None,
    enabled: bool | None = None,
    confirm: bool = False,
    expected_version: int | None = None,
) -> UserMemory:
    memory = get_or_create_current_memory(session, user_id)
    _check_version(memory, expected_version)
    mem_json = _upgrade_to_v3(memory)
    items = [deepcopy(item) for item in mem_json.get("items", []) if isinstance(item, dict)]
    target = next((item for item in items if str(item.get("id")) == item_id), None)
    if target is None:
        raise InvalidParamError("这条旅行记忆不存在或已被删除")
    if text is not None:
        clean = " ".join(text.strip().split())
        if len(clean) < 2:
            raise InvalidParamError("旅行记忆不能为空")
        target["text"] = clean
        if category is not None:
            target["category"] = category if category in CATEGORY_LABELS else "other"
    elif category is not None:
        target["category"] = category if category in CATEGORY_LABELS else "other"
    if enabled is not None:
        target["enabled"] = enabled
    if confirm:
        target["state"] = "saved"
        target["enabled"] = True
    target["updated_at"] = utcnow().isoformat()
    mem_json.update(schema_version=3, items=items)
    return _cas_write(
        session,
        memory,
        mem_json=mem_json,
        source_type="manual",
        source_id=f"patch:{item_id}:{memory.version}",
        delta={"item_id": item_id, "kind": "patch"},
        expected_version=memory.version,
    )


def delete_memory_item(
    session: Session,
    *,
    user_id: str,
    item_id: str,
    expected_version: int | None = None,
) -> UserMemory:
    memory = get_or_create_current_memory(session, user_id)
    _check_version(memory, expected_version)
    mem_json = _upgrade_to_v3(memory)
    items = [deepcopy(item) for item in mem_json.get("items", []) if isinstance(item, dict)]
    if not any(str(item.get("id")) == item_id for item in items):
        raise InvalidParamError("这条旅行记忆不存在或已被删除")
    mem_json["items"] = [item for item in items if str(item.get("id")) != item_id]
    return _cas_write(
        session,
        memory,
        mem_json=mem_json,
        source_type="manual",
        source_id=f"delete:{item_id}:{memory.version}",
        delta={"item_id": item_id, "kind": "delete"},
        expected_version=memory.version,
    )


def set_memory_enabled(
    session: Session,
    *,
    user_id: str,
    enabled: bool,
    expected_version: int | None = None,
) -> UserMemory:
    memory = get_or_create_current_memory(session, user_id)
    _check_version(memory, expected_version)
    mem_json = _upgrade_to_v3(memory)
    if bool(mem_json.get("enabled", True)) == enabled:
        return memory
    mem_json["enabled"] = enabled
    return _cas_write(
        session,
        memory,
        mem_json=mem_json,
        source_type="manual",
        source_id=f"settings:{memory.version}",
        delta={"kind": "settings", "enabled": enabled},
        expected_version=memory.version,
    )


def _check_version(memory: UserMemory, expected: int | None) -> None:
    if expected is not None and memory.version != expected:
        raise InvalidParamError("旅行记忆已更新，请刷新后重试")


def _cas_write(
    session: Session, memory: UserMemory, *, mem_json: dict, source_type: str,
    source_id: str, delta: dict, expected_version: int, trip_id: str | None = None,
) -> UserMemory:
    new_version = expected_version + 1
    memory_text = (
        _render_v3_memory_text(mem_json)
        if mem_json.get("schema_version") == 3
        else _render_memory_text(
            list(mem_json.get("preferences", [])),
            mem_json.get("planning_preferences") if isinstance(mem_json.get("planning_preferences"), dict) else None,
        )
    )
    result = session.exec(
        update(UserMemory).where(UserMemory.id == memory.id, UserMemory.version == expected_version).values(
            memory_json=mem_json, memory_text=memory_text, version=new_version,
            last_source_type=source_type, last_source_id=source_id, updated_at=utcnow(),
        )
    )
    if result.rowcount != 1:
        raise InvalidParamError("旅行记忆已更新，请刷新后重试")
    session.add(UserMemoryEvent(
        id=id_service.new_memory_event_id(), user_id=memory.user_id, memory_id=memory.id,
        trip_id=trip_id,
        source_type=source_type, source_id=source_id,
        event_key=f"{memory.user_id}:{source_type}:{source_id}",
        delta_json=delta, version_after=new_version,
    ))
    session.flush()
    session.expire(memory)
    session.refresh(memory)
    return memory
