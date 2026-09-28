"""Controlled semantic evaluation using real provider vectors and live ranking.

All texts are synthetic. Never reads or exports the runtime user database.
First run calls the configured embedding provider; later runs reuse a versioned
gzip JSON artifact. Labels are fixed in the fixture, never inferred from scores.
"""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
import gzip
import hashlib
import json
from pathlib import Path
import statistics
import sys
from time import perf_counter
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlmodel import Session, SQLModel, create_engine  # noqa: E402

import app.models.tables  # noqa: E402,F401
from app.ai.clients import discovery_embedding_client as embedding  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.models.discovery import DiscoveryPost  # noqa: E402
from app.models.dto import PlanningBrief  # noqa: E402
from app.models.plan import Plan  # noqa: E402
from app.models.report import Report  # noqa: E402
from app.models.trip import Trip  # noqa: E402
from app.models.user_memory import UserMemory  # noqa: E402
from app.services.discovery import service, semantic_sources  # noqa: E402
from app.services.discovery.ranking import preferences_from_text, rank_notes, similarity  # noqa: E402
from app.services.discovery.semantic import score_semantic  # noqa: E402
from app.services.discovery.semantic_sources import collect_evidence, post_text  # noqa: E402
from app.services.planning_intake_service import confirmation_token, finalize_brief  # noqa: E402
from evaluate_discovery import ndcg  # noqa: E402

NOW = datetime(2026, 9, 28, tzinfo=timezone.utc)
FIXTURE = ROOT / "evaluation/discovery_semantic_cases.json"
CACHE = ROOT / "evaluation/discovery_semantic_vectors.json.gz"


def fixture_posts(fixture: dict) -> list[DiscoveryPost]:
    return [DiscoveryPost(
        **{key: value for key, value in row.items() if key != "group"},
        user_id="synthetic", request_id=row["id"], author="合成案例",
        is_demo=True, created_at=NOW, photos=[],
        pitfalls="出发前核实现场开放安排，按实际情况调整。",
    ) for row in fixture["posts"]]


def insert_profile(session: Session, case: dict, user_id: str = "synthetic-reader") -> None:
    """Create real report/memory/confirmed-plan rows in an isolated database."""
    session.add(UserMemory(id="memory-" + user_id, user_id=user_id, memory_text="",
                           memory_json={"schema_version": 3, "enabled": True, "items": [
                               {"id": f"m{i}", "text": text, "state": "saved", "enabled": True}
                               for i, text in enumerate(case.get("memory", []))]}))
    trips = set()
    for i, item in enumerate(case.get("reports", [])):
        trip = user_id + ":" + item.get("trip", f"trip{i}")
        if trip not in trips:
            session.add(Trip(id=trip, user_id=user_id, title="合成旅行记录"))
            session.flush()
            trips.add(trip)
        session.add(Report(
            id=f"{user_id}:report{i}", user_id=user_id, trip_id=trip, location="合成历史地点",
            date_label="", cover_image="", personality_summary="不用于推荐的称号", content="",
            profile_version=5, created_at=NOW - timedelta(days=item.get("age", i * 7)),
            profile_data={"keywords": item["tags"], "confidence": item.get("confidence", .85),
                          "evidence_highlights": [{"asset_id": f"synthetic-asset{i}", "observed_fact": item["text"]}],
                          "persona_vector": {"dims": ["nature", "urban", "culture", "food"],
                                             "values": [item.get(dim, .1) for dim in ("nature", "urban", "culture", "food")]}}
        ))
    if case.get("plan"):
        trip = user_id + ":plan-trip"
        session.add(Trip(id=trip, user_id=user_id, title="合成的已保存行程"))
        session.flush()
        brief = finalize_brief(PlanningBrief(origin="武汉", destinations=["杭州"], start_date="2026-09-20",
                                             end_date="2026-09-21", interests=[case["plan"]]))
        session.add(Plan(id=user_id + ":plan", user_id=user_id, trip_id=trip, location="杭州",
                         date_label="", content="未被当作偏好的 AI 行程正文", updated_at=NOW,
                         itinerary_data={"trip_info": {"destination": "杭州", "start_date": "2026-09-20", "end_date": "2026-09-21", "date_label": "合成案例"},
                                         "preparations": [], "bookings": [], "food_recommendations": [], "itinerary": [],
                                         "planning_snapshot": {"brief": brief.model_dump(by_alias=True),
                                                               "confirmation_token": confirmation_token(brief),
                                                               "planning_model": "deepseek-v4-flash"}}))
    session.commit()


def prepare_case(case: dict, posts: list[DiscoveryPost]):
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session, patch.object(service, "utcnow", return_value=NOW), \
            patch.object(semantic_sources, "utcnow", return_value=NOW):
        insert_profile(session, case)
        evidence = collect_evidence(session, "synthetic-reader", posts)
        reader, _ = service.reader_context(session, "synthetic-reader", posts, {})
        query = case.get("query", "")
        if query:
            reader.destination = next((post.destination for post in posts if post.destination in query), "")
            reader.tags = preferences_from_text(query)[0]
            reader.avoid_tags -= reader.tags
    engine.dispose()
    return evidence, reader


def read_vectors(path: Path) -> dict:
    if not path.exists():
        return {"modelKey": embedding.model_key(), "model": settings.DISCOVERY_EMBEDDING_REVISION,
                "dimensions": settings.DISCOVERY_EMBEDDING_DIMENSIONS,
                "textVersion": embedding.TEXT_VERSION, "syntheticOnly": True, "entries": {}}
    result = json.loads(gzip.decompress(path.read_bytes()))
    if result["modelKey"] != embedding.model_key():
        raise RuntimeError("Embedding model changed; use a new --cache path to preserve prior evidence")
    return result


def real_vectors(texts: list[str], path: Path, offline: bool) -> dict:
    cache = read_vectors(path)
    unique = {embedding.content_hash(text): text for text in texts}
    pending = []
    for key, text in unique.items():
        row = cache["entries"].get(key)
        if row:
            embedding.unit_vector(row["vector"], settings.DISCOVERY_EMBEDDING_DIMENSIONS)
            if row["text"] != text:
                raise RuntimeError("Cached source text mismatch")
        else:
            pending.append((key, text))
    if pending and offline:
        raise RuntimeError("Missing cached real vectors; offline evaluation cannot substitute fake vectors")
    batches = [pending[i:i + 8] for i in range(0, len(pending), 8)]

    def batch_call(batch):
        start = perf_counter()
        vectors = embedding.embed_texts([text for _, text in batch])
        return vectors, perf_counter() - start

    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {pool.submit(batch_call, batch): batch for batch in batches}
        for future in as_completed(futures):
            batch = futures[future]
            vectors, elapsed = future.result()
            for (key, text), vector in zip(batch, vectors):
                cache["entries"][key] = {"text": text, "vector": vector, "fetchedAt": datetime.now(timezone.utc).isoformat()}
            cache.setdefault("batches", []).append({"count": len(batch), "seconds": round(elapsed, 3)})
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(gzip.compress(json.dumps(cache, ensure_ascii=False).encode("utf-8"), mtime=0))
            print(json.dumps({"embeddedBatch": len(batch), "seconds": round(elapsed, 3), "cachedTexts": len(cache["entries"])}), flush=True)
    return {key: embedding.unit_vector(row["vector"], settings.DISCOVERY_EMBEDDING_DIMENSIONS)
            for key, row in cache["entries"].items()}


def evaluate(cache_path: Path, offline: bool) -> dict:
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    posts = fixture_posts(fixture)
    notes = [service.as_note(post) for post in posts]
    cases = [(case, *prepare_case(case, posts)) for case in fixture["cases"]]
    vectors = real_vectors([post_text(post) for post in posts] + [item.text for _, evidence, _ in cases for item in evidence], cache_path, offline)
    post_vectors = {post.id: vectors[embedding.content_hash(post_text(post))] for post in posts}
    variants = ("rules", "centroid", "full", "no_confidence", "no_diversity")
    groups = {post["id"]: post["group"] for post in fixture["posts"]}
    detail = []
    for case, evidence, reader in cases:
        evidence_vectors = {item.id: vectors[embedding.content_hash(item.text)] for item in evidence}
        relevance = {post_id: 3 for post_id, group in groups.items() if group in case["targets"]}
        for variant in variants:
            start = perf_counter()
            semantic = score_semantic(evidence, evidence_vectors, post_vectors, variant=variant) if variant != "rules" else None
            ranking = rank_notes(notes, reader, query=case.get("query", ""), now=NOW,
                                 variant=variant if variant in {"no_confidence", "no_diversity"} else "full", semantic=semantic)
            elapsed = (perf_counter() - start) * 1000
            ids = [row.note.id for row in ranking[:10]]
            pairs = [similarity(a.note, b.note) for i, a in enumerate(ranking[:10]) for b in ranking[i + 1:10]]
            detail.append({
                "case": case["id"], "variant": variant, "top10": ids,
                "top5Groups": [groups[post_id] for post_id in ids[:5]],
                "ndcg5": round(ndcg(ids, relevance), 6),
                "precision5": sum(post_id in relevance for post_id in ids[:5]) / 5,
                "targetCoverage5": len({groups[post_id] for post_id in ids[:5]} & set(case["targets"])) / len(case["targets"]),
                "pairwiseDiversity10": round(1 - statistics.mean(pairs), 6) if pairs else 0,
                "rankingMs": round(elapsed, 3), "interestCount": len(semantic.interests) if semantic else 0,
                "confidence": round(semantic.confidence, 6) if semantic else 0,
                "evidenceSources": [{"id": e.id, "kind": e.kind, "group": e.group, "weight": round(e.weight, 6)} for e in evidence],
            })
    summary = {}
    for variant in variants:
        rows = [row for row in detail if row["variant"] == variant]
        summary[variant] = {name: round(statistics.mean(row[name] for row in rows), 6)
                            for name in ("ndcg5", "precision5", "targetCoverage5", "pairwiseDiversity10")}
        summary[variant]["medianRankingMs"] = round(statistics.median(row["rankingMs"] for row in rows), 3)
    multi = {variant: {row["case"]: row["targetCoverage5"] for row in detail
                       if row["variant"] == variant and row["case"] in {"two_interests", "minority_interest"}}
             for variant in variants}
    return {
        "fixture": str(FIXTURE.relative_to(ROOT)), "provenance": fixture["provenance"], "grading": fixture["grading"],
        "developmentNote": "首轮结果另存 discovery-semantic-evaluation-initial.json。根据首轮发现的同源信号重复计分问题修正融合逻辑；案例与标签未改。此处是开发回归结果，不是未见测试集成绩。",
        "fixedClock": NOW.isoformat(), "posts": len(posts), "cases": len(cases),
        "model": settings.DISCOVERY_EMBEDDING_REVISION, "dimensions": settings.DISCOVERY_EMBEDDING_DIMENSIONS,
        "caseSha256": hashlib.sha256(FIXTURE.read_bytes()).hexdigest(),
        "vectorArtifactSha256": hashlib.sha256(cache_path.read_bytes()).hexdigest(),
        "rankingCodeSha256": {name: hashlib.sha256((ROOT / "app/services/discovery" / name).read_bytes()).hexdigest()
                              for name in ("ranking.py", "semantic.py", "semantic_sources.py")},
        "limits": ["模型真实返回的语义向量，不是随机向量或标签哈希。", "候选、用户与标签是同一开发过程中的合成数据，存在设计偏差。",
                   "这是固定参数的控制实验；未进行训练或参数搜索，也没有显著性或真实用户效果结论。",
                   "24 篇控制笔记与原有 50 篇公开演示分开，不写入用户运行库。", "耗时只含兴趣构建与排序，不含 HTTP、数据库或模型请求。"],
        "summary": summary, "multiInterestCoverage": multi, "detail": detail,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache", type=Path, default=CACHE)
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--output", type=Path, default=ROOT.parent / "docs/discovery-semantic-evaluation.json")
    args = parser.parse_args()
    result = evaluate(args.cache, args.offline)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"summary": result["summary"], "multiInterestCoverage": result["multiInterestCoverage"]}, ensure_ascii=False, indent=2))
