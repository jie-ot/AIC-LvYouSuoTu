"""Travel notes and explicit, reversible recommendation feedback."""

from datetime import datetime
from typing import Any

from sqlalchemy import Column, Index, JSON, Text, UniqueConstraint
from sqlmodel import Field, SQLModel

from app.models.base import utcnow


class DiscoveryPost(SQLModel, table=True):
    __tablename__ = "discovery_posts"
    __table_args__ = (
        UniqueConstraint("user_id", "request_id", name="uq_discovery_publish_request"),
        Index("idx_discovery_status_created", "status", "created_at"),
    )

    id: str = Field(primary_key=True)
    user_id: str = Field(index=True)
    # Snapshots survive removal of the original trip; no cascading deletion.
    trip_id: str | None = None
    request_id: str
    author: str
    title: str
    destination: str = Field(index=True)
    body: str = Field(sa_column=Column(Text, nullable=False))
    recommendations: str = Field(default="", sa_column=Column(Text, nullable=False))
    pitfalls: str = Field(default="", sa_column=Column(Text, nullable=False))
    tags: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    photos: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    attachments: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    is_demo: bool = False
    status: str = "published"
    created_at: datetime = Field(default_factory=utcnow)


class DiscoveryFeedback(SQLModel, table=True):
    __tablename__ = "discovery_feedback"
    __table_args__ = (UniqueConstraint("user_id", "post_id", name="uq_discovery_feedback"),)

    id: str = Field(primary_key=True)
    user_id: str = Field(index=True)
    post_id: str = Field(foreign_key="discovery_posts.id", index=True)
    saved: bool = False
    dismissed: bool = False
    updated_at: datetime = Field(default_factory=utcnow)


class DiscoveryPreference(SQLModel, table=True):
    __tablename__ = "discovery_preferences"

    user_id: str = Field(primary_key=True)
    recent_searches: list[dict[str, str]] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    updated_at: datetime = Field(default_factory=utcnow)
