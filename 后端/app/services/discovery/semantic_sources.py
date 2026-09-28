"""Build travel descriptions from owned, active sources, with provenance."""

import math
import re

from sqlmodel import Session, select

from app.ai.clients.discovery_embedding_client import content_hash
from app.models.base import utcnow
from app.models.discovery import DiscoveryFeedback, DiscoveryPost
from app.models.itinerary import PlanningRequestSnapshot
from app.models.plan import Plan
from app.models.report import Report
from app.models.user_memory import UserMemory
from app.services.discovery.ranking import age_days
from app.services.discovery.semantic import Evidence
from app.services.planning_intake_service import validated_snapshot_brief


def value(data: dict, key: str, default=None):
    parts = key.split("_")
    return data.get(key, data.get(parts[0] + "".join(part.title() for part in parts[1:]), default))


def strings(values, limit: int = 12) -> list[str]:
    if not isinstance(values, list):
        return []
    return [item.strip()[:300] for item in values if isinstance(item, str) and item.strip()][:limit]


def post_text(post: DiscoveryPost) -> str:
    routes = []
    for plan in (post.attachments or {}).get("plans", [])[:4]:
        for day in plan.get("days", [])[:8]:
            routes += strings(day.get("stops", []), 12)
    # Author names, fabricated personality labels, engagement counts and
    # private reports are never matching features. Warnings retain context.
    return "\n".join([post.title, "地点：" + post.destination, post.body[:2500],
                       "推荐体验：" + post.recommendations[:1200],
                       "行前提醒：" + post.pitfalls[:700], "主题：" + "、".join(post.tags),
                       "分享路线：" + "；".join(routes)[:500]])[:5500]


def split_preferences(text: str) -> tuple[list[str], list[str]]:
    positive, negative = [], []
    for clause in re.split(r"[。；;\n，,]", text):
        clause = clause.strip()
        if not clause:
            continue
        match = re.search(r"不喜欢|不想|不要|不爱|讨厌|避免|避开|不能", clause)
        if match:
            prefix = clause[:match.start()].rstrip("但而且更我")
            denied = clause[match.end():].strip()
            if prefix:
                positive.append(prefix)
            if denied:
                negative.append(denied)
        else:
            positive.append(clause)
    return positive, negative


def _preference_evidence(key: str, text: str, kind: str, group: str, weight: float) -> list[Evidence]:
    positive, negative = split_preferences(text)
    result = []
    if positive:
        result.append(Evidence(key, "旅行偏好：" + "；".join(positive)[:1800], kind, group, weight))
    for index, clause in enumerate(negative[:6]):
        result.append(Evidence(f"{key}:avoid:{index}", "旅行体验：" + clause[:300], kind, group, weight, True))
    return result


def report_text(data: dict) -> str:
    """Only observed travel content; exclude advice about hypothetical trips."""
    parts = strings(data.get("keywords", []), 8)
    scene = value(data, "scene_signature", {}) or {}
    if isinstance(scene, dict) and value(scene, "evidence_refs", []):
        parts += strings(scene.get("tokens", []), 8)
        if scene.get("description"):
            parts.append(str(scene["description"])[:500])
    for item in value(data, "evidence_highlights", []) or []:
        if isinstance(item, dict) and value(item, "asset_id") and value(item, "observed_fact"):
            parts.append(str(value(item, "observed_fact"))[:400])
    for item in data.get("stats", []) or []:
        if isinstance(item, dict) and value(item, "asset_id"):
            parts += [str(item[key])[:200] for key in ("label", "detail") if item.get(key)]
    # Distinct keywords plus concrete observations retain fine-grained themes.
    return "；".join(dict.fromkeys(parts))[:2400]


def collect_evidence(session: Session, user_id: str, posts: list[DiscoveryPost]) -> list[Evidence]:
    now = utcnow()
    result: list[Evidence] = []
    memory = session.exec(select(UserMemory).where(UserMemory.user_id == user_id)).first()
    raw = memory.memory_json if memory and isinstance(memory.memory_json, dict) else {}
    if raw.get("enabled", True):
        for item in raw.get("items", []):
            if not isinstance(item, dict) or item.get("state") != "saved" or not item.get("enabled", True):
                continue
            text = str(item.get("text") or "").strip()
            if text:
                key = "memory:" + str(item.get("id") or content_hash(text))
                group = "trip:" + str(item["source_trip_id"]) if item.get("source_trip_id") else "memory:" + content_hash(text)
                result += _preference_evidence(key, text, "memory", group, 1.0)
        if raw.get("schema_version") != 3:
            for index, item in enumerate(raw.get("preferences", [])):
                if isinstance(item, dict) and item.get("origin") == "manual" and item.get("state") == "active":
                    text = str(item.get("summary") or "")
                    result += _preference_evidence(f"legacy-memory:{index}", text, "memory", "memory:" + content_hash(text), 1.0)
        reports = session.exec(select(Report).where(Report.user_id == user_id).order_by(Report.created_at.desc(), Report.id)).all()
        seen: set[str] = set()
        for report in reports:
            if not report.trip_id or report.trip_id in seen:
                continue
            seen.add(report.trip_id)
            data = report.profile_data if isinstance(report.profile_data, dict) else {}
            try:
                confidence = float(data.get("confidence", 0))
            except (TypeError, ValueError):
                continue
            if not math.isfinite(confidence) or not 0 < confidence <= 1:
                continue
            text = report_text(data)
            decay = 0.5 ** (age_days(report.created_at, now) / 180)
            if text:
                result.append(Evidence("report:" + report.trip_id, "这次旅行记录的场景：" + text,
                                       "report", "trip:" + report.trip_id, 0.65 * confidence * decay))
            requirements = strings(value(data, "explicit_requirements", []))
            if requirements:
                result += _preference_evidence("report-request:" + report.trip_id, "；".join(requirements),
                                               "report_request", "trip:" + report.trip_id, 0.65 * decay)
        seen_plans: set[str] = set()
        for plan in session.exec(select(Plan).where(Plan.user_id == user_id).order_by(Plan.updated_at.desc(), Plan.id)).all():
            group = "trip:" + plan.trip_id if plan.trip_id else "plan:" + plan.id
            if group in seen_plans:
                continue
            seen_plans.add(group)
            data = plan.itinerary_data if isinstance(plan.itinerary_data, dict) else {}
            try:
                saved = PlanningRequestSnapshot.model_validate(value(data, "planning_snapshot", {}))
                brief = validated_snapshot_brief(saved)
            except (TypeError, ValueError):
                continue
            if brief is None:
                continue
            # Only the confirmation record; never infer taste from the AI itinerary.
            parts = [*brief.interests, *brief.constraints, brief.transport_preference,
                     brief.lodging_preference, brief.detail_requirements]
            text = "；".join(str(part) for part in parts if part and str(part) not in {"无", "未指定"})
            result += _preference_evidence("plan-request:" + plan.id, text, "plan_request", group,
                                           0.65 * 0.5 ** (age_days(plan.updated_at, now) / 90))
    by_id = {post.id: post for post in posts}
    for action in session.exec(select(DiscoveryFeedback).where(
        DiscoveryFeedback.user_id == user_id, DiscoveryFeedback.saved == True,  # noqa: E712
        DiscoveryFeedback.dismissed == False,  # noqa: E712
    )).all():
        if action.post_id in by_id:
            result.append(Evidence("saved:" + action.post_id, post_text(by_id[action.post_id]), "saved",
                                   "saved:" + action.post_id, 0.40 * 0.5 ** (age_days(action.updated_at, now) / 90)))
    result.sort(key=lambda item: (-item.weight, item.id))
    return result[:80]
