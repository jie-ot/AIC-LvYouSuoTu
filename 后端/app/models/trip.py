"""A user-owned trip that groups plans, postcards, and reports."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Index
from sqlmodel import Field, SQLModel

from app.models.base import utcnow


class Trip(SQLModel, table=True):
    __tablename__ = "trips"
    __table_args__ = (Index("idx_trips_user_updated", "user_id", "updated_at"),)

    id: str = Field(primary_key=True)
    user_id: str = Field(index=True, nullable=False)
    title: str = Field(nullable=False)
    location: str | None = Field(default=None, nullable=True)
    start_date: str | None = Field(default=None, nullable=True)
    end_date: str | None = Field(default=None, nullable=True)
    date_label: str = Field(default="日期待定", nullable=False)
    cover_image: str | None = Field(default=None, nullable=True)
    created_at: datetime = Field(default_factory=utcnow, nullable=False)
    updated_at: datetime = Field(default_factory=utcnow, nullable=False)
