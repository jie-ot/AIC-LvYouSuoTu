"""Evidence-weighted multiple interests in a real embedding space.

No network or database access. The live service and evaluation use this code.
"""

from dataclasses import dataclass, field
import math

from app.ai.clients.discovery_embedding_client import unit_vector

Vector = tuple[float, ...]


@dataclass(frozen=True)
class Evidence:
    id: str
    text: str
    kind: str
    group: str  # one independent trip, or one distinct explicit preference
    weight: float
    negative: bool = False


@dataclass
class Interest:
    vector: Vector
    evidence: list[Evidence]
    mass: float
    reliability: float


@dataclass
class SemanticRanking:
    scores: dict[str, float] = field(default_factory=dict)
    membership: dict[str, int] = field(default_factory=dict)
    vectors: dict[str, Vector] = field(default_factory=dict)
    confidence: float = 0.0
    interests: list[Interest] = field(default_factory=list)
    coverage_enabled: bool = True


def cosine(a: Vector, b: Vector) -> float:
    if len(a) != len(b) or not a:
        return 0.0
    return max(-1.0, min(1.0, sum(x * y for x, y in zip(a, b))))


def _mass(evidence: list[Evidence]) -> float:
    groups: dict[str, float] = {}
    for item in evidence:
        groups[item.group] = max(groups.get(item.group, 0), item.weight)
    return sum(groups.values())


def _centroid(evidence: list[Evidence], vectors: dict[str, Vector]) -> Vector:
    # One independent source cannot gain strength by supplying many fields.
    grouped: dict[str, list[Evidence]] = {}
    for item in evidence:
        grouped.setdefault(item.group, []).append(item)
    sums = [0.0] * len(vectors[evidence[0].id])
    for items in grouped.values():
        total = sum(item.weight for item in items)
        group_weight = max(item.weight for item in items)
        for item in items:
            for dim, value in enumerate(vectors[item.id]):
                sums[dim] += value * item.weight / max(total, 1e-9) * group_weight
    if sum(value * value for value in sums) < 1e-12:
        return vectors[evidence[0].id]
    return unit_vector(sums)


def build_interests(evidence: list[Evidence], vectors: dict[str, Vector], *, variant: str = "full") -> list[Interest]:
    positive = [item for item in evidence if not item.negative and item.weight > 0 and item.id in vectors]
    positive.sort(key=lambda item: (-item.weight, item.id))
    clusters: list[list[Evidence]] = []
    centers: list[Vector] = []
    for item in positive:
        matches = [cosine(vectors[item.id], center) for center in centers]
        best = max(range(len(matches)), key=matches.__getitem__) if matches else -1
        if best >= 0 and (variant == "centroid" or matches[best] >= 0.76):
            clusters[best].append(item)
            centers[best] = _centroid(clusters[best], vectors)
        elif len(clusters) < 6:
            clusters.append([item])
            centers.append(vectors[item.id])
        # Keep six reliable distinct interests; unrelated weak observations
        # must not be forced into a cluster and move its meaning.
    interests = []
    for items, center in zip(clusters, centers):
        mass = _mass(items)
        interests.append(Interest(center, items, mass, 1.0 if variant == "no_confidence" else mass / (mass + 1.0)))
    return interests


def score_semantic(
    evidence: list[Evidence], evidence_vectors: dict[str, Vector],
    post_vectors: dict[str, Vector], *, variant: str = "full",
) -> SemanticRanking:
    interests = build_interests(evidence, evidence_vectors, variant=variant)
    ranking = SemanticRanking(vectors=post_vectors, interests=interests, coverage_enabled=variant != "no_diversity")
    if not interests:
        return ranking
    independent_mass = _mass([item for interest in interests for item in interest.evidence])
    ranking.confidence = 1.0 if variant == "no_confidence" else independent_mass / (independent_mass + 1.0)
    negative = [item for item in evidence if item.negative and item.id in evidence_vectors]
    for post_id, vector in post_vectors.items():
        # Generic shared travel vocabulary should carry little matching credit.
        matches = [max(0.0, (cosine(vector, interest.vector) - 0.20) / 0.80) for interest in interests]
        trusted = [value * (0.5 + 0.5 * interest.reliability) for value, interest in zip(matches, interests)]
        best = max(range(len(trusted)), key=trusted.__getitem__)
        average = sum(value * interest.mass for value, interest in zip(matches, interests)) / sum(i.mass for i in interests)
        # Best-interest matching preserves a minority interest; the mean is
        # deliberately small. Negation is a soft semantic penalty only.
        penalty = max((max(0.0, cosine(vector, evidence_vectors[item.id]) - 0.45) * min(1.0, item.weight)
                       for item in negative), default=0.0)
        ranking.scores[post_id] = max(0.0, min(1.0, 0.8 * trusted[best] + 0.2 * average - 0.25 * penalty))
        if matches[best] >= 0.20:
            ranking.membership[post_id] = best
    return ranking


def cache_vector(values: list[float], dimensions: int) -> Vector | None:
    """Fail closed on corrupt cache rows; refreshing can repair the cache."""
    try:
        if len(values) != dimensions or any(not math.isfinite(x) for x in values):
            return None
        return unit_vector(values, dimensions)
    except (TypeError, ValueError, RuntimeError):
        return None
