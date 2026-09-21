"""Idempotency record for the synchronous generation endpoint."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Column, Index, Text, UniqueConstraint
from sqlalchemy import JSON as SA_JSON
from sqlmodel import Field, SQLModel

from app.models.base import utcnow


class GenerationOperation(SQLModel, table=True):
    __tablename__ = "generation_operations"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "client_request_id", name="uq_generation_operation_user_request"
        ),
        Index("idx_generation_operations_user_created", "user_id", "created_at"),
    )

    id: str = Field(primary_key=True)
    user_id: str = Field(index=True, nullable=False)
    trip_id: str | None = Field(default=None, foreign_key="trips.id", index=True)
    client_request_id: str = Field(nullable=False)
    request_hash: str = Field(nullable=False)
    status: str = Field(default="processing", nullable=False)
    postcard_status: str = Field(default="skipped", nullable=False)
    report_status: str = Field(default="skipped", nullable=False)
    memory_status: str = Field(default="skipped", nullable=False)
    response_json: dict[str, Any] | None = Field(
        default=None, sa_column=Column(SA_JSON, nullable=True)
    )
    pending_memory_payload: dict[str, Any] | None = Field(
        default=None, sa_column=Column(SA_JSON, nullable=True)
    )
    error_message: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    created_at: datetime = Field(default_factory=utcnow, nullable=False)
    updated_at: datetime = Field(default_factory=utcnow, nullable=False)
