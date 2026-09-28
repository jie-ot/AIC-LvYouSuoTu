"""Deterministic content ranking; no provider calls or hidden engagement counts.

Explicit intent > confirmed preferences > evidence-limited travel clues.
The evaluator calls this same implementation with components ablated.
"""

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
import math
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.services.discovery.semantic import SemanticRanking

ALIASES = {
    "自然": ("自然", "山野", "山水", "森林", "草原", "湖泊"),
    "海边": ("海边", "海岸", "海岛", "沙滩", "看海", "沿海"),
    "城市漫步": ("城市漫步", "citywalk", "老街", "街巷", "街区", "街头"),
    "人文": ("人文", "博物馆", "古建", "历史", "古城", "展览"),
    "美食": ("美食", "小吃", "早茶", "夜市", "吃饭"),
    "摄影": ("摄影", "拍照", "取景", "机位"),
    "徒步": ("徒步", "登山", "爬山", "山径"),
    "自驾": ("自驾", "开车", "租车"),
    "公共交通": ("公共交通", "公交", "地铁", "高铁", "火车"),
    "慢旅行": ("慢旅行", "慢节奏", "不赶路", "不赶时间", "松弛", "休息", "放空"),
    "周末": ("周末", "两天", "二日", "一日", "短途"),
    "省心省钱": ("省心省钱", "省钱", "预算", "平价", "免费", "性价比"),
}


def preferences_from_text(text: str) -> tuple[set[str], set[str]]:
    """Only explicit preference text; negated phrases cannot become positive tags."""
    positive: set[str] = set()
    negative: set[str] = set()
    for clause in re.split(r"[，。；！!?\n,;]", text.lower()):
        for tag, words in ALIASES.items():
            for word in words:
                for match in re.finditer(re.escape(word), clause):
                    before = clause[max(0, match.start() - 10):match.start()]
                    denied = re.search(r"不喜欢|不爱|不想|不要|不考虑|避开|排除|讨厌|不去|不适合|不能", before)
                    (negative if denied else positive).add(tag)
    return positive - negative, negative


def tokens(text: str) -> list[str]:
    parts = re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]+", text.lower())
    result: list[str] = []
    for part in parts:
        if re.fullmatch(r"[\u4e00-\u9fff]+", part):
            result.extend(part[i:i + 2] for i in range(len(part) - 1))
            if len(part) == 1:
                result.append(part)
        else:
            result.append(part)
    for tag, aliases in ALIASES.items():
        if any(alias in text.lower() for alias in aliases):
            result.append("tag:" + tag)
    return result


@dataclass
class Reader:
    destination: str = ""
    intent_confidence: float = 1.0
    tags: set[str] = field(default_factory=set)
    avoid_tags: set[str] = field(default_factory=set)
    memory_tags: set[str] = field(default_factory=set)
    visited: set[str] = field(default_factory=set)
    planned: set[str] = field(default_factory=set)
    persona: dict[str, float] = field(default_factory=dict)
    persona_confidence: float = 0.0
    saved_affinity: dict[str, float] = field(default_factory=dict)
    dismissed: set[str] = field(default_factory=set)


@dataclass
class Note:
    id: str
    destination: str
    title: str
    body: str
    recommendations: str
    pitfalls: str
    tags: list[str]
    author: str
    created_at: datetime
    photo_count: int = 0

    @property
    def search_text(self) -> str:
        sections = ("推荐 " if self.recommendations else "") + (" 避雷 " if self.pitfalls else "")
        return " ".join([
            self.title, self.title, self.destination, self.destination,
            self.body, self.recommendations, self.pitfalls, " ".join(self.tags), sections,
        ])


@dataclass
class Ranked:
    note: Note
    score: float
    reasons: list[str]
    components: dict[str, float]


def place_match(left: str, right: str) -> bool:
    a, b = left.strip().lower(), right.strip().lower()
    return bool(a and b and (a in b or b in a))


def age_days(created: datetime, now: datetime) -> float:
    return max(0.0, (now.replace(tzinfo=timezone.utc) - created.replace(tzinfo=timezone.utc)).total_seconds() / 86400)


def similarity(a: Note, b: Note) -> float:
    left, right = set(a.tags), set(b.tags)
    return (
        0.5 * len(left & right) / max(1, len(left | right))
        + 0.35 * float(place_match(a.destination, b.destination))
        + 0.15 * float(a.author == b.author)
    )


def lexical_scores(notes: list[Note], query: str) -> dict[str, float]:
    """BM25 with Chinese bigrams and a small, inspectable travel synonym lexicon."""
    if not query.strip():
        return {}
    corpus = [Counter(tokens(note.search_text)) for note in notes]
    average = sum(sum(doc.values()) for doc in corpus) / max(1, len(corpus))
    terms = set(tokens(query))
    frequencies = {term: sum(term in doc for doc in corpus) for term in terms}
    scores: dict[str, float] = {}
    chunks = re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]+", query.lower())
    def matches(chunk: str, doc: Counter) -> bool:
        for tag, aliases in ALIASES.items():
            if chunk in aliases and "tag:" + tag in doc:
                return True
        terms = set(tokens(chunk))
        return len(terms & doc.keys()) / max(1, len(terms)) >= 0.6
    for note, doc in zip(notes, corpus):
        # Separate search words are ANDed. A destination plus a theme stays useful.
        if any(not matches(chunk, doc) for chunk in chunks):
            continue
        score = 0.0
        for term in terms:
            tf = doc.get(term, 0)
            if not tf:
                continue
            idf = math.log(1 + (len(notes) - frequencies[term] + 0.5) / (frequencies[term] + 0.5))
            score += idf * tf * 2.2 / (tf + 1.2 * (0.25 + 0.75 * sum(doc.values()) / max(1, average)))
        if query.lower() in note.title.lower():
            score += 2
        if place_match(query, note.destination):
            score += 3
        if score > 0:
            scores[note.id] = score
    maximum = max(scores.values(), default=1)
    return {key: value / maximum for key, value in scores.items()}


def rank_notes(
    notes: list[Note], reader: Reader, *, query: str = "", topic: str = "",
    now: datetime | None = None, variant: str = "full",
    semantic: "SemanticRanking | None" = None,
) -> list[Ranked]:
    """Variants are offline controls; UI always uses full."""
    now = now or datetime.now(timezone.utc)
    eligible = [
        note for note in notes
        if note.id not in reader.dismissed
        and not (set(note.tags) & reader.avoid_tags)
        and (not topic or topic in note.tags)
    ]
    lexical = lexical_scores(eligible, query)
    ranked: list[Ranked] = []
    for note in eligible:
        if query.strip() and note.id not in lexical:
            continue
        tags = set(note.tags)
        explicit_matches = sorted(tags & reader.tags)
        memory_matches = sorted(tags & reader.memory_tags)
        intent = float(place_match(reader.destination, note.destination))
        future = float(any(place_match(place, note.destination) for place in reader.planned))
        visited = any(place_match(place, note.destination) for place in reader.visited)
        persona = sum(reader.persona.get(tag, 0) for tag in tags) / max(1, len(tags))
        quality = (
            0.3 * min(len(note.body) / 160, 1)
            + 0.25 * bool(note.recommendations)
            + 0.25 * bool(note.pitfalls)
            + 0.2 * min(note.photo_count, 1)
        )
        components = {
            "intent": intent,
            "preference": len(explicit_matches) / max(1, len(reader.tags)),
            "memory": len(memory_matches) / max(1, len(reader.memory_tags)),
            "planned": future,
            "persona": persona,
            "feedback": sum(reader.saved_affinity.get(tag, 0) for tag in tags) / max(1, len(tags)),
            "novelty": float(bool(reader.visited) and not visited),
            "quality": quality,
            "freshness": 0.5 ** (age_days(note.created_at, now) / 60),
        }
        weights = {
            "intent": 0.44 * reader.intent_confidence if reader.destination else 0,
            "preference": 0.26 * reader.intent_confidence if reader.tags else 0,
            "memory": 0.16 if reader.memory_tags else 0,
            "planned": 0.22 if reader.planned and not reader.destination else 0,
            "persona": 0.08 * reader.persona_confidence,
            "feedback": 0.10 if reader.saved_affinity else 0,
            "novelty": 0.035 if reader.visited and not reader.destination else 0,
            "quality": 0.06,
            "freshness": 0.04,
        }
        if semantic and note.id in semantic.scores and variant not in {"recent", "content", "rules"}:
            # These coarse features describe the SAME records already encoded
            # in the semantic interests. Use them as a fallback, not a second
            # vote that can swamp another independent interest.
            encoded_kinds = {e.kind for interest in semantic.interests for e in interest.evidence}
            if encoded_kinds & {"memory", "report_request"}:
                weights["memory"] = 0
            if "report" in encoded_kinds:
                weights["persona"] = 0
            if "saved" in encoded_kinds:
                weights["feedback"] = 0
        if variant == "no_intent":
            weights["intent"] = weights["planned"] = 0
        if variant == "no_confidence" and not (semantic and semantic.interests):
            weights["persona"] = 0.08 if reader.persona else 0
        if variant == "content":
            all_tags = reader.tags | reader.memory_tags
            components["preference"] = len(tags & all_tags) / max(1, len(all_tags))
            weights = {key: 0.0 for key in weights}
            weights.update(preference=0.8, quality=0.1, freshness=0.1)
        if variant == "recent":
            weights = {key: float(key == "freshness") for key in weights}
        score = sum(weights[key] * value for key, value in components.items()) / max(sum(weights.values()), 0.01)
        if semantic and note.id in semantic.scores and variant not in {"recent", "content", "rules"}:
            # On the home feed, accumulated interests become the main personal
            # signal. A concrete current destination retains priority.
            semantic_weight = (0.22 if reader.destination or reader.planned or query.strip() else 0.65) * semantic.confidence
            components["semantic"] = semantic.scores[note.id]
            score = (score * sum(weights.values()) + semantic_weight * components["semantic"]) / (sum(weights.values()) + semantic_weight)
        reasons: list[str] = []
        if intent and weights["intent"]:
            reasons.append("匹配近期检索的目的地：" + reader.destination)
        elif future and weights["planned"]:
            reasons.append("与你接下来的行程目的地相符")
        if explicit_matches:
            reasons.append("匹配近期搜索主题：" + "、".join(explicit_matches[:2]))
        elif memory_matches and weights["memory"]:
            reasons.append("符合已确认的" + "、".join(memory_matches[:2]) + "偏好")
        if not reasons and components["feedback"] > 0.05:
            reasons.append("与你收藏的旅行主题相近")
        if not reasons and persona > 0.15 and reader.persona_confidence > 0:
            reasons.append("与你旅行照片中的主题线索相近")
        if query.strip():
            score = 0.78 * lexical[note.id] + 0.22 * score
            components["search"] = lexical[note.id]
            reasons.insert(0, "匹配搜索关键词")
        if not reasons:
            reasons = ["换个目的地看看" if reader.visited and not visited else "发现一种旅行方式"]
        ranked.append(Ranked(note, score, reasons[:2], components))
    ranked.sort(key=lambda item: (-item.score, item.note.id))
    if variant in {"no_diversity", "recent", "content"}:
        return ranked
    result: list[Ranked] = []
    # Score the entire candidate pool before slicing pages, so adjacent pages
    # do not restart diversity selection or repeat notes.
    strength = 0.08 if query.strip() or reader.destination or reader.planned else 0.16
    redundancy = {item.note.id: 0.0 for item in ranked}
    coverage: dict[int, int] = {}
    def coverage_bonus(item: Ranked) -> float:
        if not semantic or not semantic.coverage_enabled or reader.destination or reader.planned or query.strip():
            return 0.0
        interest = semantic.membership.get(item.note.id)
        return (0.06 * semantic.confidence * semantic.scores.get(item.note.id, 0) / (1 + coverage.get(interest, 0))) if interest is not None else 0.0
    while ranked:
        chosen = max(
            ranked,
            key=lambda item: item.score - strength * redundancy[item.note.id] + coverage_bonus(item),
        )
        result.append(chosen)
        ranked.remove(chosen)
        if semantic and chosen.note.id in semantic.membership:
            interest = semantic.membership[chosen.note.id]
            coverage[interest] = coverage.get(interest, 0) + 1
        for item in ranked:
            duplicate = similarity(item.note, chosen.note)
            if semantic and item.note.id in semantic.vectors and chosen.note.id in semantic.vectors:
                from app.services.discovery.semantic import cosine
                dense = max(0.0, (cosine(semantic.vectors[item.note.id], semantic.vectors[chosen.note.id]) - 0.25) / 0.75)
                duplicate = 0.55 * duplicate + 0.45 * dense
            redundancy[item.note.id] = max(redundancy[item.note.id], duplicate)
    return result
