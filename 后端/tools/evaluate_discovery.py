"""Reproducible synthetic ranking evaluation, with explicit limits.

Run from the backend: python tools/evaluate_discovery.py
No external providers, runtime DB, or generated relevance labels.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import statistics
import sys
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.discovery.demo import demo_posts  # noqa: E402
from app.services.discovery.ranking import Reader, rank_notes, similarity  # noqa: E402
from app.services.discovery.service import as_note  # noqa: E402


def ndcg(ids: list[str], relevance: dict[str, int], k: int = 5) -> float:
    def dcg(grades):
        return sum((2 ** grade - 1) / math.log2(index + 2) for index, grade in enumerate(grades))
    ideal = dcg(sorted(relevance.values(), reverse=True)[:k])
    return dcg([relevance.get(post_id, 0) for post_id in ids[:k]]) / ideal if ideal else 0


def evaluate() -> dict:
    case_path = ROOT / "evaluation/discovery_cases.json"
    fixture = json.loads(case_path.read_text(encoding="utf-8"))
    now = datetime(2026, 9, 28, tzinfo=timezone.utc)
    notes = [as_note(post) for post in demo_posts()]
    variants = ("recent", "content", "no_intent", "no_confidence", "no_diversity", "full")
    detail = []
    for case in fixture["cases"]:
        data = case["reader"].copy()
        for name in ("tags", "avoid_tags", "memory_tags", "visited", "planned", "dismissed"):
            if name in data:
                data[name] = set(data[name])
        reader = Reader(**data)
        for variant in variants:
            start = perf_counter()
            ranking = rank_notes(notes, reader, now=now, variant=variant)
            elapsed = (perf_counter() - start) * 1000
            first = ranking[:10]
            ids = [item.note.id for item in first]
            pairs = [similarity(a.note, b.note) for index, a in enumerate(first) for b in first[index + 1:]]
            detail.append({
                "case": case["id"], "variant": variant, "top10": ids,
                "ndcg5": round(ndcg(ids, case["relevance"]), 6),
                "precision5": sum(case["relevance"].get(post_id, 0) >= 2 for post_id in ids[:5]) / 5,
                "destinationCount10": len({item.note.destination for item in first}),
                "pairwiseDiversity10": round(1 - statistics.mean(pairs), 6) if pairs else 0,
                "rankingMs": round(elapsed, 3),
            })
    summary = {}
    for variant in variants:
        rows = [row for row in detail if row["variant"] == variant]
        summary[variant] = {
            name: round(statistics.mean(row[name] for row in rows), 6)
            for name in ("ndcg5", "precision5", "destinationCount10", "pairwiseDiversity10")
        }
        summary[variant]["medianRankingMs"] = round(statistics.median(row["rankingMs"] for row in rows), 3)
    cold = {}
    for variant in ("recent", "no_diversity", "full"):
        ranking = rank_notes(notes, Reader(), now=now, variant=variant)
        cold[variant] = {
            "destinationCount10": len({item.note.destination for item in ranking[:10]}),
            "top10": [item.note.id for item in ranking[:10]],
        }
    serial = [{"id": note.id, "text": note.search_text, "date": note.created_at.isoformat()} for note in notes]
    return {
        "dataset": "50 条原创合成旅行笔记", "cases": len(fixture["cases"]),
        "relevanceSource": fixture["provenance"],
        "fixedClock": now.isoformat(),
        "caseSha256": hashlib.sha256(case_path.read_bytes()).hexdigest(),
        "datasetSha256": hashlib.sha256(json.dumps(serial, ensure_ascii=False, sort_keys=True).encode()).hexdigest(),
        "limits": [
            "笔记、需求案例和相关性标签均为同一开发过程中的合成材料，存在设计者偏差。",
            "用于机制验证，不能据此宣称真实用户满意度、点击率或行业领先。",
            "未训练或拟合模型；权重为预先指定的工程参数，没有用本评测作参数搜索。",
            "时间指标只含 50 条候选的本机纯排序计算，不含数据库、HTTP 或 AI。",
        ],
        "summary": summary, "coldStart": cold, "detail": detail,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT.parent / "docs/discovery-evaluation.json")
    args = parser.parse_args()
    result = evaluate()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "summary": result["summary"], "coldStart": result["coldStart"]}, ensure_ascii=False, indent=2))
