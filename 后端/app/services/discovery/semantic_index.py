"""Non-blocking feed reads and versioned, source-checked background indexing."""

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
import hashlib
import logging
from threading import Lock
from time import monotonic

from sqlalchemy import Engine
from sqlmodel import Session, select

from app.ai.clients import discovery_embedding_client as embedding
from app.core.config import settings
from app.models.base import utcnow
from app.models.discovery import DiscoveryPost
from app.models.discovery_embedding import DiscoveryEmbedding
from app.services.discovery.semantic import Evidence, SemanticRanking, cache_vector, score_semantic
from app.services.discovery.semantic_sources import collect_evidence, post_text

logger = logging.getLogger("lvyousuotu")
_refresh_lock = Lock()
_retry_after: dict[str, float] = {}


@dataclass(frozen=True)
class Document:
    scope: str
    source_id: str
    text: str

    @property
    def hash(self) -> str:
        return embedding.content_hash(self.text)

    @property
    def cache_id(self) -> str:
        return hashlib.sha256((self.scope + "\0" + self.source_id + "\0" + embedding.model_key()).encode()).hexdigest()


def documents(user_id: str, posts: list[DiscoveryPost], evidence: list[Evidence]) -> list[Document]:
    return [Document("public", post.id, post_text(post)) for post in posts] + [
        Document("user:" + user_id, item.id, item.text) for item in evidence
    ]


def _rows(session: Session, user_id: str) -> dict[str, DiscoveryEmbedding]:
    return {row.id: row for row in session.exec(select(DiscoveryEmbedding).where(
        DiscoveryEmbedding.scope.in_(["public", "user:" + user_id]),
        DiscoveryEmbedding.model_key == embedding.model_key(),
    )).all()}


def _cached(document: Document, rows: dict[str, DiscoveryEmbedding]):
    row = rows.get(document.cache_id)
    if not row or row.content_hash != document.hash:
        return None
    return cache_vector(row.vector, settings.DISCOVERY_EMBEDDING_DIMENSIONS)


def read_semantic(session: Session, user_id: str, posts: list[DiscoveryPost]) -> tuple[SemanticRanking, dict]:
    """No network call, writes, or stale profile reuse on the feed path."""
    metadata = {
        "status": "disabled", "model": settings.DISCOVERY_EMBEDDING_REVISION,
        "dimensions": settings.DISCOVERY_EMBEDDING_DIMENSIONS, "indexedPosts": 0,
        "totalPosts": len(posts), "evidenceCount": 0, "interestCount": 0,
    }
    if not settings.DISCOVERY_SEMANTIC_ENABLED:
        return SemanticRanking(), metadata
    if not settings.ARK_PLAN_API_KEY:
        metadata["status"] = "unavailable"
        return SemanticRanking(), metadata
    evidence = collect_evidence(session, user_id, posts)
    requested = documents(user_id, posts, evidence)
    rows = _rows(session, user_id)
    post_vectors, user_vectors = {}, {}
    missing = 0
    for document in requested:
        vector = _cached(document, rows)
        if vector is None:
            missing += 1
        elif document.scope == "public":
            post_vectors[document.source_id] = vector
        else:
            user_vectors[document.source_id] = vector
    # One page must use one consistent scoring scale. Until the source snapshot
    # is fully indexed, use the rule baseline for every candidate; otherwise
    # uncached notes could outrank cached ones just because their denominator
    # omits semantic scoring. Successful batches remain reusable on disk.
    ranking = score_semantic(evidence, user_vectors, post_vectors) if not missing else SemanticRanking()
    cooling_down = _retry_after.get(user_id, 0) > monotonic()
    metadata.update(
        status="ready" if not missing else "unavailable" if cooling_down else "building",
        indexedPosts=len(post_vectors), evidenceCount=len(user_vectors),
        interestCount=len(ranking.interests), missingCount=missing,
        sources={kind: sum(item.kind == kind and item.id in user_vectors for item in evidence)
                 for kind in {item.kind for item in evidence}},
    )
    return ranking, metadata


def _snapshot(session: Session, user_id: str) -> list[Document]:
    posts = list(session.exec(select(DiscoveryPost).where(DiscoveryPost.status == "published")).all())
    return documents(user_id, posts, collect_evidence(session, user_id, posts))


def refresh_user_index(user_id: str, db_engine: Engine | None = None) -> dict:
    """Background task; successful batches survive a later provider failure."""
    if not settings.DISCOVERY_SEMANTIC_ENABLED or not settings.ARK_PLAN_API_KEY:
        return {"status": "disabled", "embedded": 0}
    if _retry_after.get(user_id, 0) > monotonic() or not _refresh_lock.acquire(blocking=False):
        return {"status": "deferred", "embedded": 0}
    try:
        if db_engine is None:
            from app.db.session import engine
            db_engine = engine
        with Session(db_engine) as session:
            current = _snapshot(session, user_id)
            rows = _rows(session, user_id)
            pending = [document for document in current if _cached(document, rows) is None]
            active = {document.cache_id for document in current}
            # Also prune superseded model versions and removed/disabled sources.
            for row in session.exec(select(DiscoveryEmbedding).where(
                DiscoveryEmbedding.scope.in_(["public", "user:" + user_id]),
            )).all():
                if row.id not in active:
                    session.delete(row)
            session.commit()
        batch_size = max(1, min(16, settings.DISCOVERY_EMBEDDING_BATCH_SIZE))
        batches = [pending[index:index + batch_size] for index in range(0, len(pending), batch_size)]
        embedded, failed = 0, False
        with ThreadPoolExecutor(max_workers=max(1, min(4, settings.DISCOVERY_EMBEDDING_PARALLELISM))) as pool:
            futures = {pool.submit(embedding.embed_texts, [doc.text for doc in batch]): batch for batch in batches}
            for future in as_completed(futures):
                batch = futures[future]
                try:
                    vectors = future.result()
                    if len(vectors) != len(batch):
                        raise embedding.EmbeddingUnavailable("invalid_batch")
                    with Session(db_engine) as session:
                        # An item may have been deleted, disabled or edited while
                        # awaiting the provider. Do not resurrect its old vector.
                        latest = {doc.cache_id: doc.hash for doc in _snapshot(session, user_id)}
                        for doc, vector in zip(batch, vectors):
                            if latest.get(doc.cache_id) != doc.hash:
                                continue
                            session.merge(DiscoveryEmbedding(
                                id=doc.cache_id, scope=doc.scope, source_id=doc.source_id,
                                model_key=embedding.model_key(), content_hash=doc.hash,
                                vector=list(vector), updated_at=utcnow(),
                            ))
                            embedded += 1
                        session.commit()
                except Exception:
                    failed = True
                    logger.warning("Discovery embedding batch unavailable; retaining valid cached vectors")
        if failed:
            _retry_after[user_id] = monotonic() + 60
        else:
            _retry_after.pop(user_id, None)
        return {"status": "partial" if failed else "ready", "embedded": embedded}
    except Exception:
        _retry_after[user_id] = monotonic() + 60
        logger.warning("Discovery semantic refresh unavailable; using existing recommendations")
        return {"status": "unavailable", "embedded": 0}
    finally:
        _refresh_lock.release()
