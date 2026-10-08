"""Automatic, reversible summaries of independent photo journeys.

Photo frequency is weak evidence for choosing optional activities. It never
establishes transport, budget, health, companions, or a permanent personality.
Generated schedules are deliberately excluded to avoid learning from ourselves.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import date
import hashlib
import json
import math


SOURCE_KIND = "automatic_observation"
SCENES = {
    "coast": ("湖泊、河流与海岸水景", ("coast",)),
    "nature": ("山水与自然景观", ("nature", "mountain")),
    "culture": ("历史建筑与老城街区", ("culture",)),
    "city": ("城市街区与夜景", ("city", "street", "night")),
    "food": ("当地饮食", ("food",)),
}


def _number(value: object) -> int:
    try:
        return max(0, int(value))
    except (ValueError, TypeError, OverflowError):
        return 0


def _day(observation: dict) -> date | None:
    days = []
    raw_days = observation.get("photo_dates")
    for raw in raw_days if isinstance(raw_days, list) else []:
        try:
            parsed = date.fromisoformat(str(raw)[:10])
            if parsed <= date.today():
                days.append(parsed)
        except ValueError:
            continue
    return max(days, default=None)


def _fingerprint(observation: dict) -> str:
    fingerprint = str(observation.get("source_fingerprint") or "")
    if fingerprint:
        return fingerprint
    # Legacy snapshots have no checksums. Conservatively collapse equivalent
    # dated observations, rather than crediting re-uploaded photos as new trips.
    value = {key: observation.get(key) for key in (
        "photo_dates", "photo_count", "photo_location_labels", "observed_facts",
    )}
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _scene_count(observation: dict, scene: str, tags: tuple[str, ...]) -> int:
    counts = observation.get("travel_type_counts")
    if isinstance(counts, dict):
        return _number(counts.get(scene))
    evidence = observation.get("scene_evidence", {})
    if not isinstance(evidence, dict):
        return 0
    return len({
        str(row["asset_id"])
        for tag in tags for row in (evidence.get(tag) or [])
        if isinstance(row, dict) and row.get("asset_id")
    })


def consolidate(raw: dict | None) -> dict:
    """Recompute derived memories; preserve edits, opt-outs and source notes."""
    memory = deepcopy(raw) if isinstance(raw, dict) else {}
    raw_items = memory.get("items")
    items = [item for item in raw_items if isinstance(item, dict)] if isinstance(raw_items, list) else []
    previous = {str(item.get("id")): item for item in items if item.get("source_kind") == SOURCE_KIND}
    explicit = [item for item in items if item.get("source_kind") != SOURCE_KIND]
    reserved = {str(item.get("id")) for item in explicit}
    suppressed = set(memory.get("dismissed_automatic_ids") or [])
    observations = memory.get("trip_observations", {})
    observations = observations if isinstance(observations, dict) else {}
    unique: dict[str, tuple[str, dict]] = {}
    for trip_id, observation in sorted(observations.items(), key=lambda pair: str(pair[1].get("updated_at", "")) if isinstance(pair[1], dict) else "", reverse=True):
        if not isinstance(observation, dict) or _number(observation.get("photo_count")) < 3:
            continue
        unique.setdefault(_fingerprint(observation), (str(trip_id), observation))
    episodes = list(unique.values())
    latest = max((day for _, row in episodes if (day := _day(row))), default=date.today())
    weights = {
        trip_id: 2 ** (-max(0, (latest - (_day(row) or latest)).days) / 365)
        for trip_id, row in episodes
    }
    inferred = []
    for scene, (label, tags) in SCENES.items():
        item_id = f"automatic_scene_{scene}"
        if item_id in reserved or item_id in suppressed:
            continue
        support, shares = [], []
        for trip_id, row in episodes:
            total = _number(row.get("photo_count"))
            count = min(total, _scene_count(row, scene, tags))
            threshold = max(2, math.ceil(total * .2))
            if not isinstance(row.get("travel_type_counts"), dict):
                threshold = min(8, threshold)  # Old evidence lists were capped.
            shares.append(weights[trip_id] * count / total)
            if count >= threshold:
                support.append((trip_id, row))
        if not support:
            continue
        salience = sum(shares) / max(.01, sum(weights.values()))
        if salience < .15:
            continue
        support_count = len(support)
        old = previous.get(item_id, {})
        timestamp = max((str(row.get("updated_at") or "") for _, row in support), default="")
        observed = f"{support_count} 次独立旅行的照片中较多出现{label}"
        inferred.append({
            "id": item_id,
            "text": f"{observed}；本次条件合适时，可作为选择活动的轻量参考",
            "category": "food" if scene == "food" else "attractions",
            "state": "saved", "enabled": bool(old.get("enabled", True)),
            "source_kind": SOURCE_KIND,
            "source_pattern_id": f"pattern_travel_type_{scene}",
            "source_trip_ids": [trip_id for trip_id, _ in support],
            "photo_source_trip_ids": [trip_id for trip_id, _ in support],
            "support_count": support_count,
            "salience": round(salience, 3),
            # A bounded evidence weight, not a calibrated personality probability.
            "confidence": round(min(.8, .25 + .1 * support_count + .2 * salience), 2),
            "created_at": str(old.get("created_at") or timestamp),
            "updated_at": timestamp,
        })
    inferred.sort(key=lambda item: (-item["salience"], -item["support_count"], item["id"]))
    memory["items"] = [*explicit, *inferred[:3]]
    return memory
