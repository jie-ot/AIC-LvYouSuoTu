"""Model-internal output schemas (《后端与大模型通信接口规范》七).

These constrain MODEL output only; they do not replace front/back-end DTOs.
`ItineraryData` is reused from the contract (1.9) and `ReportChartPoint` from
1.7. Any new field that affects DTO/persistence/response must be reflected in
the contract spec first.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.models.dto import CamelModel, PlanningBrief, ReportChartPoint, TravelProfileData

__all__ = [
    "PhotoAnalysisItem",
    "PhotoAnalysisResult",
    "PostcardSelectionItem",
    "PostcardSelectionResult",
    "PostcardTypeStyle",
    "PostcardPlanItem",
    "PostcardPlanResult",
    "PostcardCritiqueResult",
    "ReportCopyResult",
    "ReportNextStopCopy",
    "ReportStatNote",
    "ReportChartPoint",
    "ReportDraftResult",
    "MemoryUpdateResult",
    "PlanningIntakeResult",
]


class PhotoAnalysisItem(BaseModel):
    asset_id: str
    scene_summary: str
    location_guess: str | None = None
    taken_date_guess: str | None = None
    suitability: Literal["good", "usable", "unsuitable"]
    postcard_reason: str | None = None
    report_reason: str | None = None
    observed_facts: list[str] = Field(default_factory=list)
    scene_tags: list[
        Literal[
            "nature",
            "city",
            "culture",
            "food",
            "night",
            "coast",
            "mountain",
            "street",
            "other",
        ]
    ] = Field(default_factory=list)
    shot_scale: Literal["wide", "medium", "close"] | None = None
    analysis_confidence: float = Field(default=0.5, ge=0, le=1)


class PhotoAnalysisResult(BaseModel):
    photos: list[PhotoAnalysisItem]
    overall_location: str | None = None
    start_date: str | None = None
    end_date: str | None = None


class PostcardSelectionItem(BaseModel):
    source_asset_ids: list[str]


class PostcardSelectionResult(BaseModel):
    items: list[PostcardSelectionItem]


class PostcardTypeStyle(BaseModel):
    """Typography direction passed to the image model."""

    family: Literal[
        "modern_sans",
        "condensed_sans",
        "editorial_serif",
        "rounded_display",
        "handwritten",
        "stencil",
        "monospace",
    ] = "modern_sans"
    composition: Literal[
        "quiet_corner",
        "oversized_crop",
        "vertical_spine",
        "split_stack",
        "outline_echo",
        "angled_label",
        "center_stage",
    ] = "quiet_corner"
    treatment: Literal[
        "solid",
        "outline",
        "offset_shadow",
        "duotone",
        "translucent",
        "paper_cutout",
    ] = "solid"
    scale: Literal["review_reduced", "restrained", "balanced", "bold", "hero"] = "balanced"
    color_role: Literal[
        "auto_contrast",
        "source_dark",
        "source_light",
        "source_accent",
        "complementary",
    ] = "auto_contrast"
    rotation_degrees: int = Field(default=0, ge=-12, le=12)


class PostcardPlanItem(BaseModel):
    series_motif: str
    design_concept: str
    photo_transformation: str
    visual_device: str
    typography: str
    type_style: PostcardTypeStyle = Field(default_factory=PostcardTypeStyle)
    canvas_format: Literal[
        "landscape_3_2",
        "landscape_4_3",
        "landscape_16_9",
        "square_1_1",
        "portrait_4_5",
        "portrait_2_3",
    ] = "landscape_3_2"
    layout_style: Literal[
        "editorial_full_bleed",
        "paper_portal",
        "split_echo",
        "tactile_collage",
        "contact_sheet",
        "contour_cutout",
        "map_grid",
        "color_field",
    ] = "editorial_full_bleed"
    visual_medium: Literal[
        "editorial_photo",
        "cinematic_photo",
        "risograph",
        "screenprint",
        "gouache",
        "linocut",
        "mixed_media",
        "graphic_flat",
    ] = "editorial_photo"
    palette_strategy: Literal[
        "source_harmony",
        "source_accent",
        "duotone",
        "complementary",
        "monochrome_pop",
        "sun_faded",
    ] = "source_harmony"
    title_placement: Literal[
        "top_left", "top_right", "bottom_left", "bottom_right"
    ] = "bottom_left"
    text_rendering: Literal["model_integrated"] = "model_integrated"
    title: str
    source_asset_ids: list[str]
    extra_texts: list[str] = Field(default_factory=list)
    emblem_style: Literal[
        "none", "monogram", "seal", "geometric_mark"
    ] = "none"
    emblem_text: str = ""
    image_prompt: str


class PostcardPlanResult(BaseModel):
    items: list[PostcardPlanItem]


class PostcardCritiqueResult(BaseModel):
    """One bounded visual review of the finished postcard preview."""

    approved: bool
    fidelity_score: int = Field(ge=0, le=10)
    artistry_score: int = Field(ge=0, le=10)
    composition_score: int = Field(ge=0, le=10)
    typography_score: int = Field(ge=0, le=10)
    finish_score: int = Field(ge=0, le=10)
    template_risk_score: int = Field(ge=0, le=10)
    blocking_issues: list[Literal[
        "subject_changed",
        "location_fabricated",
        "subject_occluded",
        "text_illegible",
        "text_cropped",
        "text_duplicated",
        "random_text_or_logo",
        "severe_artifact",
        "unsafe_content",
    ]] = Field(default_factory=list, max_length=5)
    issues: list[str] = Field(default_factory=list, max_length=5)
    repair_target: Literal["none", "image", "typography", "both"] = "none"
    repair_instruction: str = Field(default="", max_length=300)
    typography_adjustment: Literal[
        "none",
        "reduce_scale",
        "increase_contrast",
        "move_opposite_corner",
        "simplify_treatment",
    ] = "none"


class ReportStatNote(BaseModel):
    id: str
    caption: str = Field(min_length=3, max_length=20)


class ReportNextStopCopy(BaseModel):
    title: str = Field(min_length=2, max_length=10)
    destination: str = Field(min_length=2, max_length=10)
    reason: str = Field(min_length=4, max_length=26)


class ReportCopyResult(BaseModel):
    """Editorial layer over the computed 旅格; every field is validated separately."""

    journey_title: str = Field(min_length=3, max_length=14)
    tagline: str = Field(min_length=6, max_length=26)
    portrait: str = Field(min_length=24, max_length=90)
    trip_word: str = Field(min_length=1, max_length=1)
    trip_word_note: str = Field(min_length=3, max_length=18)
    stat_notes: list[ReportStatNote] = Field(default_factory=list, max_length=3)
    moment_line: str = Field(min_length=6, max_length=30)
    next_continue: ReportNextStopCopy
    next_contrast: ReportNextStopCopy


class ReportDraftResult(BaseModel):
    location: str
    start_date: str | None
    end_date: str | None
    personality_summary: str
    content: str
    chart_data: list[ReportChartPoint]
    profile_data: TravelProfileData


class MemoryUpdateResult(BaseModel):
    add_preferences: list[str] = []
    weaken_preferences: list[str] = []
    evidence_summary: str
    confidence: float
    source_task: Literal["generate", "plan_save", "plan_update"]


class PlanningIntakeResult(CamelModel):
    """Model-produced conversational reply plus the cumulative requirement state."""

    assistant_message: str
    brief: PlanningBrief
