"""Outward DTOs — the single front/back-end contract.

Master definition: 《数据结构与通信接口规范》一、三. Field names, types,
optionality and enums are the project's unique contract; compatibility changes
must be additive and optional. All outward DTOs are camelCase via `to_camel`; the
`ItineraryData` family stays snake_case (see `app.models.itinerary`).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic.alias_generators import to_camel

from app.ai.model_selection import DEFAULT_PLANNING_MODEL, PlanningModel
from app.models.itinerary import ItineraryData

# Outward enums (mirrored from the DB enum table & 1.4/1.5/1.7).
RadarDimension = Literal["自然探索", "人文体验", "美食偏好", "慢节奏", "社交意愿"]
VisualTheme = Literal[
    "forest_light",
    "ocean_blue",
    "sunset_orange",
    "museum_gold",
    "city_neon",
    "night_purple",
    "snow_silver",
    "desert_amber",
]
# Fixed radar dimension order for stable chart rendering.
RADAR_DIMENSIONS: tuple[RadarDimension, ...] = (
    "自然探索",
    "人文体验",
    "美食偏好",
    "慢节奏",
    "社交意愿",
)

UsageType = Literal["upload", "generated_postcard", "generated_report_cover", "system"]
AssetStatus = Literal["temporary", "attached", "deleted"]
OwnerType = Literal["postcard_group", "postcard", "report", "plan", "user_memory"]
ReferenceRole = Literal[
    "source_photo", "postcard_image", "report_cover", "plan_attachment", "memory_evidence"
]


class CamelModel(BaseModel):
    """Base for outward DTOs: camelCase aliases, accept both names on input."""

    model_config = ConfigDict(
        alias_generator=to_camel,
        validate_by_name=True,
        validate_by_alias=True,
        serialize_by_alias=True,
    )


# —— 1.2 Postcard ——
class Postcard(CamelModel):
    id: str
    title: str
    image_url: str
    source_asset_ids: list[str] = Field(default_factory=list)
    render_mode: Literal["ai_composite", "local_fallback", "local_no_text", "legacy"] | None = None
    prompt_version: str | None = None


# —— 1.1 PostcardGroup ——
class PostcardGroup(CamelModel):
    id: str
    trip_id: str | None = None
    location: str
    start_date: str | None
    end_date: str | None
    date_label: str
    cover_image: str
    postcards: list[Postcard]


# —— 1.7 ReportChartPoint ——
class ReportChartPoint(CamelModel):
    dimension: RadarDimension
    value: int


class ProfileSpectrum(CamelModel):
    id: Literal["environment", "depth", "planning", "social"]
    left_label: str
    right_label: str
    value: int


class ProfileTraitAssessment(CamelModel):
    id: Literal["environment", "depth", "planning", "social"]
    value: int
    confidence: float = Field(ge=0, le=1)
    evidence_refs: list[str] = Field(default_factory=list)
    assessment: Literal["supported", "undetermined"]


class SceneSignature(CamelModel):
    title: str
    tokens: list[str] = Field(min_length=1, max_length=4)
    description: str
    evidence_refs: list[str] = Field(default_factory=list)


class EvidenceHighlight(CamelModel):
    asset_id: str
    image_url: str | None = None
    observed_fact: str
    trait_id: Literal["scene", "environment", "depth", "planning", "social"]
    contribution: str


class NextTripExperiment(CamelModel):
    kind: Literal["continue", "contrast"]
    title: str
    reason: str
    planning_prompt: str
    evidence_refs: list[str] = Field(default_factory=list)


class ProfileModule(CamelModel):
    title: str
    content: str


class MusicRecommendation(CamelModel):
    title: str
    reason: str
    mood: str


class TravelProfileData(CamelModel):
    archetype_id: str
    archetype_name: str
    persona_code: str
    slogan: str
    summary: str | None = None
    spectrums: list[ProfileSpectrum]
    keywords: list[str]
    modules: list[ProfileModule]
    strengths: list[str] = Field(default_factory=list)
    watchouts: list[str] = Field(default_factory=list)
    best_scenarios: list[str] = Field(default_factory=list)
    action_tips: list[str] = Field(default_factory=list)
    next_trip_inspiration: str
    music_recommendation: MusicRecommendation | None = None
    travel_prescription: str | None = None
    souvenir_line: str | None = None
    visual_theme: VisualTheme
    sample_quality: Literal["low", "medium", "high"] = "low"
    confidence: float = Field(default=0, ge=0, le=1)
    traits: list[ProfileTraitAssessment] = Field(default_factory=list)
    scope_note: str = "仅根据本次旅行的照片和你填写的要求生成。"
    scene_signature: SceneSignature | None = None
    evidence_highlights: list[EvidenceHighlight] = Field(default_factory=list, max_length=3)
    next_trip_experiments: list[NextTripExperiment] = Field(default_factory=list, max_length=2)
    explicit_requirements: list[str] = Field(default_factory=list)


# —— 1.6 Report ——
class Report(CamelModel):
    id: str
    trip_id: str | None = None
    location: str
    start_date: str | None
    end_date: str | None
    date_label: str
    cover_image: str
    personality_summary: str
    content: str
    chart_data: list[ReportChartPoint]
    profile_version: int | None = None
    profile_data: TravelProfileData | None = None
    source_images: list[str] = Field(default_factory=list)


# —— 1.8 Plan —— (itineraryData stays snake_case)
class Plan(CamelModel):
    id: str
    trip_id: str | None = None
    location: str
    start_date: str | None
    end_date: str | None
    date_label: str
    content: str
    itinerary_data: ItineraryData


class TripSummary(CamelModel):
    id: str
    title: str
    location: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    date_label: str
    cover_image: str | None = None
    plan_count: int = 0
    postcard_count: int = 0
    report_count: int = 0
    updated_at: str


class TripDetail(TripSummary):
    plans: list[Plan] = Field(default_factory=list)
    postcard_groups: list[PostcardGroup] = Field(default_factory=list)
    reports: list[Report] = Field(default_factory=list)


# —— 1.4 FileAsset ——
class FileAsset(CamelModel):
    id: str
    relative_path: str
    mime_type: str
    size_bytes: int
    usage_type: UsageType
    status: AssetStatus
    ref_count: int


# —— 1.3 UploadedPhoto ——
class UploadedPhoto(CamelModel):
    asset_id: str
    image_url: str
    taken_at: str | None
    location: str | None


# —— 1.5 FileAssetReference ——
class FileAssetReference(CamelModel):
    id: str
    user_id: str
    asset_id: str
    owner_type: OwnerType
    owner_id: str
    role: ReferenceRole
    created_at: str


# —— Upload response (#4) ——
class UploadResult(CamelModel):
    asset_id: str
    image_url: str


# —— Generate response (#5) ——
class GenerateResult(CamelModel):
    postcard_group: PostcardGroup | None
    report: Report | None
    trip: TripSummary | None = None
    operation_id: str | None = None
    status: Literal["completed", "partial", "failed"] = "completed"
    postcard_status: Literal["success", "failed", "skipped"] = "skipped"
    report_status: Literal["success", "failed", "skipped"] = "skipped"
    memory_status: Literal["success", "failed", "skipped", "pending"] = "skipped"
    warnings: list["GenerationWarning"] = Field(default_factory=list)


class GenerationWarning(CamelModel):
    code: str
    message: str
    feature: Literal["postcard", "report", "memory", "input", "system"]
    item_index: int | None = None
    retryable: bool = False


# ============================================================
# Request bodies
# ============================================================


class GenerateOptions(CamelModel):
    generate_postcards: bool
    generate_report: bool
    postcard_count: int | None = Field(default=None, ge=1, le=5)
    learn_preferences: bool = False


class GenerateRequest(CamelModel):
    photos: list[UploadedPhoto] = Field(min_length=1, max_length=50)
    requirements: str = Field(max_length=1000)
    # Kept separate from artwork instructions so users know exactly what can
    # become a reusable planning memory. None preserves older clients.
    memory_requirements: str | None = Field(default=None, max_length=1000)
    options: GenerateOptions
    client_request_id: str | None = Field(default=None, min_length=8, max_length=64)
    trip_id: str | None = None


PlanningPhase = Literal["collecting", "confirming", "completed"]
PlanningMessageRole = Literal["user", "assistant"]
PlanningChecklistStatus = Literal["ready", "assumed", "missing"]


class PlanningChatMessage(CamelModel):
    role: PlanningMessageRole
    content: str
    # Optional for backward compatibility. New clients stamp every real turn so
    # the stateless endpoint can reject model switching inside one conversation.
    planning_model: PlanningModel | None = None


class PlanningBrief(CamelModel):
    """Structured requirement state accumulated across planning chat turns."""

    origin: str | None = None
    destinations: list[str] = Field(default_factory=list)
    start_date: str | None = None
    end_date: str | None = None
    traveler_count: int | None = None
    budget: str | None = None
    transport_preference: str | None = None
    lodging_preference: str | None = None
    interests: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    summary: str = ""
    # Free-form leftovers the structured fields cannot carry: city order,
    # morning/evening windows, party constraints, must-sees, etc. Shown on the
    # confirmation checklist and re-injected verbatim into generation.
    detail_requirements: str = ""

    @field_validator(
        "destinations", "interests", "constraints", "assumptions", mode="before"
    )
    @classmethod
    def normalize_nullable_lists(cls, value):  # noqa: ANN001, ANN206
        """Model-facing compatibility: JSON null means no accumulated items."""
        return [] if value is None else value

    @field_validator("summary", "detail_requirements", mode="before")
    @classmethod
    def normalize_nullable_summary(cls, value):  # noqa: ANN001, ANN206
        return "" if value is None else value


class PlanningChecklistItem(CamelModel):
    key: str
    label: str
    value: str
    status: PlanningChecklistStatus
    required: bool


class PlanningRequest(CamelModel):
    message: str
    planning_model: PlanningModel = DEFAULT_PLANNING_MODEL
    # New plans collect requirements first. Existing plans may still be refined
    # directly by passing context + confirmed=true.
    context: ItineraryData | None = None
    messages: list[PlanningChatMessage] = Field(default_factory=list)
    brief: PlanningBrief | None = None
    confirmed: bool = False
    # Stateless digest of the exact normalized brief shown to the user. New
    # requirement turns receive a new token, so a stale checklist can never
    # trigger generation after the user has changed the trip requirements.
    confirmation_token: str | None = Field(default=None, max_length=64)
    # Client-generated, optional. When present the backend publishes stage
    # progress the client can poll while this request is still in flight.
    progress_token: str | None = Field(default=None, max_length=64)


class PlanningResponse(CamelModel):
    phase: PlanningPhase
    assistant_message: str
    planning_model: PlanningModel
    brief: PlanningBrief | None = None
    checklist: list[PlanningChecklistItem] = Field(default_factory=list)
    confirmation_token: str | None = None
    itinerary: ItineraryData | None = None


class PlanSaveRequest(CamelModel):
    itinerary_data: ItineraryData
    trip_id: str | None = None


class TripCreateRequest(CamelModel):
    title: str = Field(min_length=1, max_length=120)
    location: str | None = Field(default=None, max_length=120)
    start_date: str | None = None
    end_date: str | None = None


class TripUpdateRequest(CamelModel):
    title: str = Field(min_length=1, max_length=120)


# ============================================================
# User-facing travel memory display
# ============================================================


class MemoryDisplayItem(CamelModel):
    id: str
    icon: str
    title: str
    content: str
    planning_hint: str | None = None
    source_labels: list[str] = Field(default_factory=list)
    editable: bool = True
    state: Literal["candidate", "active"] = "active"
    origin: Literal["inferred", "manual", "explicit_requirement"] = "manual"
    confidence: float = Field(default=0, ge=0, le=1)
    confirmation_text: str | None = None
    legacy_observation: bool = False
    enabled: bool = True
    category: str = "other"
    source_trip_id: str | None = None
    source_label: str | None = None


class TravelMemoryStats(CamelModel):
    trip_count: int = 0
    place_count: int = 0
    photo_count: int = 0
    plan_count: int = 0


class TravelMemoryFootprint(CamelModel):
    id: str
    trip_id: str
    title: str
    location: str | None = None
    date_label: str
    cover_image: str | None = None
    state: Literal["recorded", "planned", "undated"] = "recorded"
    state_label: str
    source_labels: list[str] = Field(default_factory=list)
    travel_types: list[str] = Field(default_factory=list)
    highlights: list[str] = Field(default_factory=list)
    pace_label: str | None = None
    photo_count: int = 0
    plan_count: int = 0


class TravelMemoryPattern(CamelModel):
    id: str
    title: str
    content: str
    category: str
    source_kind: Literal["photos", "plans", "combined"]
    support_count: int = 1
    source_trip_ids: list[str] = Field(default_factory=list)
    source_labels: list[str] = Field(default_factory=list)
    confirmable: bool = False
    confirmed: bool = False
    planning_text: str | None = None


class MemoryPlanningPreferenceField(CamelModel):
    key: str
    label: str
    value: str = ""
    placeholder: str
    helper: str
    editable: bool = True


class TravelMemoryDisplay(CamelModel):
    intro: str | None = None
    overview_title: str | None = None
    overview_content: str | None = None
    planning_preferences: list[MemoryPlanningPreferenceField] = Field(default_factory=list)
    memories: list[MemoryDisplayItem] = Field(default_factory=list)
    stats: TravelMemoryStats = Field(default_factory=TravelMemoryStats)
    footprints: list[TravelMemoryFootprint] = Field(default_factory=list)
    patterns: list[TravelMemoryPattern] = Field(default_factory=list)
    editable: bool = True
    updated_at: str | None = None
    version: int
    is_empty: bool = False
    enabled: bool = True
    legacy_count: int = 0


class MemoryDescriptionUpdateRequest(CamelModel):
    title: str = Field(max_length=80)
    content: str = Field(max_length=500)
    expected_version: int | None = Field(default=None, ge=1)


class MemoryOverviewUpdateRequest(CamelModel):
    title: str = Field(max_length=80)
    content: str = Field(max_length=800)
    expected_version: int | None = Field(default=None, ge=1)


class MemoryPlanningPreferencesUpdateRequest(CamelModel):
    transport: str = Field(default="", max_length=300)
    hotel: str = Field(default="", max_length=300)
    attractions: str = Field(default="", max_length=300)
    food: str = Field(default="", max_length=300)
    pace: str = Field(default="", max_length=300)
    other: str = Field(default="", max_length=500)
    expected_version: int | None = Field(default=None, ge=1)


class MemoryItemCreateRequest(CamelModel):
    text: str = Field(min_length=2, max_length=500)
    category: str = Field(default="other", max_length=40)
    expected_version: int | None = Field(default=None, ge=1)


class MemoryItemPatchRequest(CamelModel):
    text: str | None = Field(default=None, min_length=2, max_length=500)
    category: str | None = Field(default=None, max_length=40)
    enabled: bool | None = None
    confirm: bool = False
    expected_version: int | None = Field(default=None, ge=1)


class MemorySettingsUpdateRequest(CamelModel):
    enabled: bool
    expected_version: int | None = Field(default=None, ge=1)


class MemoryPatternConfirmRequest(CamelModel):
    expected_version: int | None = Field(default=None, ge=1)
