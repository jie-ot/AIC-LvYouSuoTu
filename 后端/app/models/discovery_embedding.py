"""Content-addressed semantic cache; stores vectors, not copies of private text."""

from datetime import datetime

from sqlalchemy import Column, JSON
from sqlmodel import Field, SQLModel

from app.models.base import utcnow


class DiscoveryEmbedding(SQLModel, table=True):
    __tablename__ = "discovery_embeddings"

    id: str = Field(primary_key=True)
    scope: str = Field(index=True)  # public notes, or one user's private evidence
    source_id: str
    model_key: str = Field(index=True)
    content_hash: str
    vector: list[float] = Field(sa_column=Column(JSON, nullable=False))
    updated_at: datetime = Field(default_factory=utcnow)
