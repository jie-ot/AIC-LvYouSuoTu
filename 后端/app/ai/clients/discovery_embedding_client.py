"""Real, version-checked Ark embeddings. Never substitutes synthetic vectors."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Sequence

from app.core.config import settings

TEXT_VERSION = "travel-evidence-v1"


class EmbeddingUnavailable(RuntimeError):
    pass


def model_key() -> str:
    payload = [settings.ARK_PLAN_BASE_URL.rstrip("/"), settings.DISCOVERY_EMBEDDING_MODEL,
               settings.DISCOVERY_EMBEDDING_REVISION, settings.DISCOVERY_EMBEDDING_DIMENSIONS, TEXT_VERSION]
    return hashlib.sha256(json.dumps(payload).encode()).hexdigest()


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def unit_vector(values: Sequence[float], dimensions: int | None = None) -> tuple[float, ...]:
    if not values or (dimensions is not None and len(values) != dimensions):
        raise EmbeddingUnavailable("invalid_dimensions")
    if any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) for value in values):
        raise EmbeddingUnavailable("invalid_vector")
    length = math.sqrt(sum(value * value for value in values))
    if length < 1e-9:
        raise EmbeddingUnavailable("zero_vector")
    return tuple(value / length for value in values)


def embed_texts(texts: list[str]) -> list[tuple[float, ...]]:
    """One bounded batch. Callers persist successful batches independently."""
    if not texts:
        return []
    if not settings.DISCOVERY_SEMANTIC_ENABLED or not settings.ARK_PLAN_API_KEY:
        raise EmbeddingUnavailable("not_configured")
    if any(not text.strip() or len(text) > 6000 for text in texts):
        raise EmbeddingUnavailable("invalid_text")
    from openai import OpenAI

    # The dedicated Agent Plan endpoint is already configured for this app.
    with OpenAI(api_key=settings.ARK_PLAN_API_KEY, base_url=settings.ARK_PLAN_BASE_URL,
                max_retries=0, timeout=settings.DISCOVERY_EMBEDDING_TIMEOUT_SECONDS) as client:
        try:
            result = client.embeddings.create(
                model=settings.DISCOVERY_EMBEDDING_MODEL, input=texts,
                dimensions=settings.DISCOVERY_EMBEDDING_DIMENSIONS, encoding_format="float",
            )
        except Exception as exc:
            # No provider response, request text, URL or credentials in errors.
            raise EmbeddingUnavailable("provider_unavailable") from exc
    if result.model != settings.DISCOVERY_EMBEDDING_REVISION:
        raise EmbeddingUnavailable("model_revision_changed")
    data = sorted(result.data, key=lambda item: item.index)
    if [item.index for item in data] != list(range(len(texts))):
        raise EmbeddingUnavailable("invalid_batch")
    return [unit_vector(item.embedding, settings.DISCOVERY_EMBEDDING_DIMENSIONS) for item in data]
