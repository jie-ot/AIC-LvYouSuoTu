from typing import Literal

from pydantic import ConfigDict, Field, field_validator

from app.models.dto import CamelModel

TAGS = (
    "自然", "海边", "城市漫步", "人文", "美食", "摄影",
    "徒步", "自驾", "公共交通", "慢旅行", "周末", "省心省钱",
)


class SearchInput(CamelModel):
    model_config = ConfigDict(populate_by_name=True, str_strip_whitespace=True, extra="forbid")
    query: str = Field(min_length=1, max_length=100)


class PostInput(CamelModel):
    model_config = ConfigDict(populate_by_name=True, str_strip_whitespace=True, extra="forbid")
    request_id: str = Field(min_length=8, max_length=80)
    trip_id: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=2, max_length=60)
    destination: str = Field(min_length=1, max_length=60)
    body: str = Field(min_length=2, max_length=5000)
    recommendations: str = Field(default="", max_length=2000)
    pitfalls: str = Field(default="", max_length=2000)
    tags: list[str] = Field(default_factory=list, max_length=8)
    photo_asset_ids: list[str] = Field(default_factory=list, max_length=12)
    report_ids: list[str] = Field(default_factory=list, max_length=4)
    postcard_ids: list[str] = Field(default_factory=list, max_length=8)
    plan_ids: list[str] = Field(default_factory=list, max_length=4)

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, values: list[str]) -> list[str]:
        if any(value not in TAGS for value in values):
            raise ValueError("请选择已有的旅行标签")
        return list(dict.fromkeys(values))

    @field_validator("photo_asset_ids", "report_ids", "postcard_ids", "plan_ids")
    @classmethod
    def unique_ids(cls, values: list[str]) -> list[str]:
        if any(not value or len(value) > 80 for value in values):
            raise ValueError("素材标识无效")
        return list(dict.fromkeys(values))


class FeedbackInput(CamelModel):
    action: Literal["save", "unsave", "dismiss", "restore"]


class AssistInput(CamelModel):
    model_config = ConfigDict(populate_by_name=True, str_strip_whitespace=True, extra="forbid")
    destination: str = Field(default="", max_length=60)
    title: str = Field(default="", max_length=60)
    body: str = Field(default="", max_length=5000)
    recommendations: str = Field(default="", max_length=2000)
    pitfalls: str = Field(default="", max_length=2000)


class TagEvidence(CamelModel):
    tag: str = Field(max_length=20)
    evidence: str = Field(min_length=1, max_length=150)


class AssistResult(CamelModel):
    title: str = Field(min_length=2, max_length=60)
    body: str = Field(min_length=2, max_length=5000)
    tags: list[TagEvidence] = Field(default_factory=list, max_length=8)
