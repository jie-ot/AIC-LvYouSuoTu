"""Map stored travel memory to a compact, user-managed list."""

from __future__ import annotations

from datetime import datetime

from sqlmodel import Session

from app.models.dto import MemoryDisplayItem, TravelMemoryDisplay
from app.models.user_memory import UserMemory
from app.services import memory_insight_service
from app.services.memory_service import CATEGORY_LABELS, _upgrade_to_v3

ICONS = {
    "transport": "↗",
    "hotel": "⌂",
    "pace": "◷",
    "food": "◇",
    "accessibility": "◎",
    "budget": "¥",
    "attractions": "○",
    "other": "·",
}


class MemoryDisplayAdapter:
    """Expose concrete memories; archived photo inferences stay hidden."""

    def to_display(
        self,
        memory: UserMemory,
        *,
        session: Session | None = None,
        user_id: str | None = None,
    ) -> TravelMemoryDisplay:
        mem_json = _upgrade_to_v3(memory)
        items: list[MemoryDisplayItem] = []
        for raw in mem_json.get("items", []):
            if not isinstance(raw, dict):
                continue
            content = str(raw.get("text") or "").strip()
            if not content:
                continue
            category = str(raw.get("category") or "other")
            state = "candidate" if raw.get("state") == "suggested" else "active"
            source_trip_id = str(raw.get("source_trip_id") or "").strip() or None
            source_kind = str(raw.get("source_kind") or "manual")
            source_trip_ids = [
                str(value) for value in raw.get("source_trip_ids", []) if value
            ] if isinstance(raw.get("source_trip_ids"), list) else []
            if source_kind == "observed_pattern":
                source_label = f"根据 {len(source_trip_ids)} 次旅行确认"
            else:
                source_label = (
                    str(raw.get("source_trip_title") or "").strip()
                    or ("旅行中填写" if source_trip_id else "手动添加")
                )
            items.append(MemoryDisplayItem(
                id=str(raw.get("id")),
                icon=ICONS.get(category, "·"),
                title=CATEGORY_LABELS.get(category, "其他"),
                content=content,
                source_labels=[source_label],
                editable=True,
                state=state,
                origin=(
                    "explicit_requirement"
                    if source_kind == "explicit_requirement"
                    else "inferred" if source_kind == "observed_pattern" else "manual"
                ),
                confidence=1.0 if state == "active" else 0.0,
                confirmation_text=content if state == "candidate" else None,
                enabled=bool(raw.get("enabled", state == "active")),
                category=category,
                source_trip_id=source_trip_id,
                source_label=source_label,
            ))
        stats, footprints, patterns = (
            memory_insight_service.build_context(session, user_id, mem_json)
            if session is not None and user_id
            else (None, [], [])
        )
        overview = mem_json.get("display_overview")
        overview_title = None
        overview_content = None
        if isinstance(overview, dict):
            overview_title = str(overview.get("title") or "").strip() or None
            overview_content = str(overview.get("content") or "").strip() or None
        return TravelMemoryDisplay(
            overview_title=overview_title,
            overview_content=overview_content,
            memories=items,
            planning_preferences=[],
            stats=stats or {},
            footprints=footprints,
            patterns=patterns,
            editable=True,
            updated_at=self._format_datetime(memory.updated_at),
            version=memory.version,
            is_empty=not items and not footprints and not patterns,
            enabled=bool(mem_json.get("enabled", True)),
            legacy_count=sum(
                isinstance(item, dict) for item in mem_json.get("legacy_items", [])
            ),
        )

    def source_text_for_description(self, memory: UserMemory, description_id: str) -> list[str]:
        mem_json = _upgrade_to_v3(memory)
        return [
            str(item.get("text") or "")
            for item in mem_json.get("items", [])
            if isinstance(item, dict) and str(item.get("id")) == description_id
        ]

    @staticmethod
    def _format_datetime(value: datetime | None) -> str | None:
        return value.isoformat() if value is not None else None
