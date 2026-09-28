"""Analytic vectors test mechanics only; real-provider quality is evaluated separately."""

from datetime import timedelta
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

import app.models.tables  # noqa: F401
from app.ai.clients import discovery_embedding_client as embedding
from app.core.config import settings
from app.models.base import utcnow
from app.models.discovery import DiscoveryFeedback, DiscoveryPost
from app.models.discovery_embedding import DiscoveryEmbedding
from app.models.dto import PlanningBrief
from app.models.plan import Plan
from app.models.report import Report
from app.models.trip import Trip
from app.models.user_memory import UserMemory
from app.services.discovery import semantic_index as index
from app.services.discovery import service
from app.services.discovery.ranking import Reader, rank_notes
from app.services.discovery.semantic import Evidence, build_interests, score_semantic
from app.services.discovery.semantic_sources import collect_evidence, post_text, report_text
from app.services.planning_intake_service import confirmation_token, finalize_brief


def fake_embed(texts):
    return [(1.0, 0.0, 0.0, 0.0) if "海" in text else (0.0, 1.0, 0.0, 0.0) for text in texts]


class SemanticTests(unittest.TestCase):
    def setUp(self):
        for key, value in {"DISCOVERY_SEMANTIC_ENABLED": True, "DISCOVERY_EMBEDDING_DIMENSIONS": 4,
                           "ARK_PLAN_API_KEY": "unit-test-not-a-key"}.items():
            override = patch.object(settings, key, value)
            override.start()
            self.addCleanup(override.stop)
        index._retry_after.clear()
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        SQLModel.metadata.create_all(self.engine)
        self.session = Session(self.engine)
        self.addCleanup(self.engine.dispose)
        self.addCleanup(self.session.close)
        self.posts = [DiscoveryPost(id="sea", user_id="writer", author="海", request_id="sea-request",
                                   title="海岸上的下午", destination="厦门", body="海风吹过，停下来看看浪。", tags=["海边"]),
                      DiscoveryPost(id="museum", user_id="writer", author="城", request_id="museum-request",
                                   title="博物馆里的细节", destination="杭州", body="仔细看器物，慢慢走。", tags=["人文"])]
        self.session.add_all(self.posts)
        self.session.add(Trip(id="trip", user_id="reader", title="旅行"))
        self.session.commit()

    def memory(self, text="喜欢海风和安静的岸边", user="reader", enabled=True):
        row = UserMemory(id="memory-" + user, user_id=user, memory_text="", memory_json={
            "schema_version": 3, "enabled": enabled, "items": [
                {"id": "chosen", "text": text, "state": "saved", "enabled": True},
                {"id": "pending", "text": "PRIVATE_PENDING", "state": "pending", "enabled": True},
            ]})
        self.session.add(row)
        self.session.commit()
        return row

    def report(self, name="report", **changes):
        values = dict(id=name, user_id="reader", trip_id="trip", location="杭州", date_label="", cover_image="",
                      personality_summary="PRIVATE_ARCHETYPE", content="PRIVATE_MODEL_PROSE",
                      profile_data={"confidence": .8, "keywords": ["瓷器", "古建筑"],
                                    "next_stops": [{"reason": "PRIVATE_SUGGESTION"}]})
        values.update(changes)
        row = Report(**values)
        self.session.add(row)
        self.session.commit()
        return row

    def refresh(self):
        with patch.object(embedding, "embed_texts", side_effect=fake_embed) as provider:
            result = index.refresh_user_index("reader", self.engine)
        self.session.expire_all()
        return result, provider

    def test_cache_reuse_and_feed_never_calls_provider(self):
        self.memory()
        result, provider = self.refresh()
        self.assertEqual(result["embedded"], 3)
        self.assertGreater(provider.call_count, 0)
        result, provider = self.refresh()
        self.assertEqual(result["embedded"], 0)
        self.assertEqual(provider.call_count, 0)
        with patch.object(embedding, "embed_texts", side_effect=AssertionError("network on feed")):
            feed = service.feed(self.session, "reader")
        self.assertEqual(feed["semantic"]["status"], "ready")
        self.assertEqual(feed["items"][0]["id"], "sea")

    def test_private_memory_cannot_cross_users(self):
        self.memory()
        self.refresh()
        semantic, state = index.read_semantic(self.session, "other", self.posts)
        self.assertEqual(semantic.scores, {})
        self.assertEqual(state["evidenceCount"], 0)
        self.assertEqual(state["indexedPosts"], 2)

    def test_changed_memory_immediately_stops_old_vector(self):
        row = self.memory()
        self.refresh()
        row = self.session.get(UserMemory, row.id)
        row.memory_json = {**row.memory_json, "items": [{"id": "chosen", "text": "喜欢细看展品", "state": "saved", "enabled": True}]}
        self.session.add(row)
        self.session.commit()
        semantic, state = index.read_semantic(self.session, "reader", self.posts)
        self.assertEqual(state["status"], "building")
        self.assertFalse(semantic.scores)
        self.refresh()
        self.assertEqual(service.feed(self.session, "reader")["items"][0]["id"], "museum")

    def test_disabled_memory_ignores_reports_but_keeps_explicit_saves(self):
        self.memory(enabled=False)
        self.report()
        self.session.add(DiscoveryFeedback(id="saved", user_id="reader", post_id="sea", saved=True))
        self.session.commit()
        evidence = collect_evidence(self.session, "reader", self.posts)
        self.assertEqual([item.kind for item in evidence], ["saved"])

    def test_deleted_memory_cache_is_pruned(self):
        row = self.memory()
        self.refresh()
        self.session.delete(row)
        self.session.commit()
        self.refresh()
        private = self.session.exec(select(DiscoveryEmbedding).where(DiscoveryEmbedding.scope == "user:reader")).all()
        self.assertEqual(private, [])

    def test_report_sources_are_trip_deduplicated_and_grounded(self):
        self.report("older", created_at=utcnow() - timedelta(days=2))
        self.report("newer")
        evidence = collect_evidence(self.session, "reader", self.posts)
        self.assertEqual(len(evidence), 1)
        self.assertIn("古建筑", evidence[0].text)
        self.assertNotIn("PRIVATE", evidence[0].text)
        self.assertEqual(evidence[0].group, "trip:trip")

    def test_uncertain_or_foreign_report_is_not_evidence(self):
        self.report(profile_data={"confidence": float("nan"), "keywords": ["海边"]})
        self.report("foreign", user_id="other", trip_id=None)
        self.assertEqual(collect_evidence(self.session, "reader", self.posts), [])

    def test_saved_plan_uses_confirmation_not_generated_itinerary(self):
        brief = finalize_brief(PlanningBrief(origin="武汉", destinations=["杭州"], start_date="2030-10-01",
                                             end_date="2030-10-03", interests=["细看古建筑"], transport_preference="公共交通"))
        snapshot = {"brief": brief.model_dump(by_alias=True), "confirmation_token": confirmation_token(brief),
                    "planning_model": "deepseek-v4-flash"}
        self.session.add(Plan(id="plan", user_id="reader", trip_id="trip", location="杭州", date_label="", content="PRIVATE_AI_PLAN",
                              itinerary_data={"planning_snapshot": snapshot, "itinerary": [{"activity": "PRIVATE_AI_PLAN"}]}))
        self.session.commit()
        evidence = collect_evidence(self.session, "reader", self.posts)
        self.assertEqual(len(evidence), 1)
        self.assertIn("古建筑", evidence[0].text)
        self.assertNotIn("PRIVATE", evidence[0].text)

    def test_unconfirmed_plan_cannot_become_preference(self):
        self.session.add(Plan(id="plan", user_id="reader", location="海边", date_label="", content="我喜欢海边",
                              itinerary_data={"planning_snapshot": {"brief": {}, "confirmation_token": "fake"}}))
        self.session.commit()
        self.assertEqual(collect_evidence(self.session, "reader", self.posts), [])

    def test_negative_preference_is_not_positive_interest(self):
        self.memory("不喜欢徒步，喜欢海边")
        evidence = collect_evidence(self.session, "reader", self.posts)
        positive = [item.text for item in evidence if not item.negative]
        self.assertTrue(all("徒步" not in text for text in positive))
        self.assertTrue(any(item.negative and "徒步" in item.text for item in evidence))

    def test_source_change_during_provider_call_cannot_resurrect_memory(self):
        self.memory()
        def delayed(texts):
            with Session(self.engine) as session:
                memory = session.get(UserMemory, "memory-reader")
                memory.memory_json = {"schema_version": 3, "enabled": False, "items": []}
                session.add(memory)
                session.commit()
            return fake_embed(texts)
        with patch.object(embedding, "embed_texts", side_effect=delayed):
            index.refresh_user_index("reader", self.engine)
        self.session.expire_all()
        self.assertEqual(len(self.session.exec(select(DiscoveryEmbedding).where(DiscoveryEmbedding.scope == "user:reader")).all()), 0)

    def test_provider_failure_returns_rules_and_retry_cooldown(self):
        self.memory()
        with patch.object(embedding, "embed_texts", side_effect=embedding.EmbeddingUnavailable("offline")) as provider:
            first = index.refresh_user_index("reader", self.engine)
            second = index.refresh_user_index("reader", self.engine)
        self.assertEqual(first["status"], "partial")
        self.assertEqual(second["status"], "deferred")
        self.assertEqual(provider.call_count, 1)
        feed = service.feed(self.session, "reader")
        self.assertEqual(feed["semantic"]["status"], "unavailable")
        self.assertEqual(feed["total"], 2)

    def test_changed_model_and_corrupt_vector_are_cache_misses(self):
        self.memory()
        self.refresh()
        with patch.object(settings, "DISCOVERY_EMBEDDING_REVISION", "another-model"):
            self.assertEqual(index.read_semantic(self.session, "reader", self.posts)[1]["indexedPosts"], 0)
        row = self.session.exec(select(DiscoveryEmbedding).where(DiscoveryEmbedding.source_id == "sea")).one()
        row.vector = [0.0] * 4
        self.session.add(row)
        self.session.commit()
        self.assertEqual(index.read_semantic(self.session, "reader", self.posts)[1]["indexedPosts"], 1)

    def test_post_text_change_invalidates_only_that_post(self):
        self.refresh()
        post = self.session.get(DiscoveryPost, "sea")
        post.body = "海岸的另一种体验"
        self.session.add(post)
        self.session.commit()
        result, _ = self.refresh()
        self.assertEqual(result["embedded"], 1)

    def test_incomplete_index_uses_one_rule_scale_and_can_pin_pagination(self):
        self.memory()
        before = service.feed(self.session, "reader", limit=1)
        self.assertEqual(before["semantic"]["status"], "building")
        expected = service.feed(self.session, "reader", use_semantic=False)
        self.refresh()
        following = service.feed(self.session, "reader", offset=1, use_semantic=False)
        self.assertEqual(before["items"][0]["id"], expected["items"][0]["id"])
        self.assertEqual([p["id"] for p in following["items"]], [p["id"] for p in expected["items"][1:]])
        post = self.session.get(DiscoveryPost, "sea")
        post.body = "新的海边内容"
        self.session.add(post)
        self.session.commit()
        semantic, state = index.read_semantic(self.session, "reader", self.posts)
        self.assertEqual(state["status"], "building")
        self.assertEqual(semantic.scores, {})

    def test_semantics_replace_the_same_coarse_memory_vote(self):
        self.memory()
        self.refresh()
        semantic, _ = index.read_semantic(self.session, "reader", self.posts)
        notes = [service.as_note(post) for post in self.posts]
        now = utcnow()
        a = rank_notes(notes, Reader(memory_tags={"海边"}), semantic=semantic, now=now)
        b = rank_notes(notes, Reader(), semantic=semantic, now=now)
        self.assertEqual([(p.note.id, p.score) for p in a], [(p.note.id, p.score) for p in b])

    def test_confirmed_future_destination_still_overrides_historical_taste(self):
        self.memory()
        self.refresh()
        semantic, _ = index.read_semantic(self.session, "reader", self.posts)
        semantic.confidence = 1.0
        semantic.scores = {"sea": 1.0, "museum": .1}
        notes = [service.as_note(post) for post in self.posts]
        ranking = rank_notes(notes, Reader(planned={"杭州"}), semantic=semantic)
        self.assertEqual(ranking[0].note.id, "museum")

    def test_semantics_cannot_resurrect_hidden_or_override_search(self):
        self.memory()
        self.refresh()
        service.set_feedback(self.session, "reader", "sea", "dismiss")
        self.session.commit()
        self.assertEqual([item["id"] for item in service.feed(self.session, "reader")["items"]], ["museum"])
        self.assertEqual(service.feed(self.session, "reader", query="杭州")["items"][0]["id"], "museum")

    def test_post_attachments_do_not_embed_private_personality_reports(self):
        self.posts[0].attachments = {"reports": [{"content": "PRIVATE_REPORT"}],
                                     "plans": [{"days": [{"stops": ["湖畔步行"]}]}]}
        text = post_text(self.posts[0])
        self.assertIn("湖畔步行", text)
        self.assertNotIn("PRIVATE_REPORT", text)
        self.assertNotIn("建议", report_text({"keywords": ["古建"], "next_trip_inspiration": "建议去海边"}))


class SemanticMathTests(unittest.TestCase):
    def test_multiple_interests_preserve_minority_over_centroid(self):
        evidence = [Evidence(f"city{i}", "古建", "report", f"trip{i}", 1.0) for i in range(5)]
        evidence.append(Evidence("sea", "海岸", "memory", "sea", 1.0))
        vectors = {item.id: (1.0, 0.0) for item in evidence}
        vectors["sea"] = (0.0, 1.0)
        items = {"sea_note": (0.0, 1.0)}
        multi = score_semantic(evidence, vectors, items)
        single = score_semantic(evidence, vectors, items, variant="centroid")
        self.assertEqual(len(multi.interests), 2)
        self.assertGreater(multi.scores["sea_note"], single.scores["sea_note"])

    def test_repeated_fields_from_same_trip_do_not_inflate_confidence(self):
        one = [Evidence("a", "古建", "report", "trip", .5)]
        repeated = one + [Evidence("b", "古建", "report_request", "trip", .5)]
        vectors = {"a": (1.0, 0.0), "b": (1.0, 0.0)}
        self.assertEqual(score_semantic(one, vectors, {}).confidence, score_semantic(repeated, vectors, {}).confidence)
        self.assertEqual(build_interests(repeated, vectors)[0].mass, .5)

    def test_invalid_provider_vectors_and_version_fail_closed(self):
        for vector in ([0, 0], [float("nan"), 1], [True, 1]):
            with self.assertRaises(embedding.EmbeddingUnavailable):
                embedding.unit_vector(vector, 2)
        with patch.object(settings, "ARK_PLAN_API_KEY", "test-key"), patch("openai.OpenAI") as client:
            client.return_value.__enter__.return_value.embeddings.create.return_value = SimpleNamespace(model="wrong-version", data=[])
            with self.assertRaisesRegex(embedding.EmbeddingUnavailable, "model_revision_changed"):
                embedding.embed_texts(["公开演示文字"])

    def test_no_sources_is_true_cold_start(self):
        result = score_semantic([], {}, {"post": (1.0, 0.0)})
        self.assertEqual(result.scores, {})
        self.assertEqual(result.confidence, 0)


if __name__ == "__main__":
    unittest.main()
