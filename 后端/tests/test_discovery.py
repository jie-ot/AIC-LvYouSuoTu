"""Behavior tests against isolated SQLite, including the actual API envelope."""

from datetime import timedelta
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

import app.models.tables  # noqa: F401
from app.core.dependencies import get_current_user_id
from app.core.config import settings
from app.core.exceptions import InvalidParamError
from app.db.session import get_session
from app.main import create_app
from app.models.base import utcnow
from app.models.discovery import DiscoveryFeedback
from app.models.file_asset import FileAsset
from app.models.file_asset_reference import FileAssetReference
from app.models.plan import Plan
from app.models.postcard import Postcard
from app.models.postcard_group import PostcardGroup
from app.models.report import Report
from app.models.trip import Trip
from app.models.user_memory import UserMemory
from app.services.discovery import service
from app.services.discovery.demo import demo_posts, ensure_demo_posts
from app.services.discovery.ranking import Reader, preferences_from_text, rank_notes
from app.services.discovery.schemas import AssistInput, PostInput


class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        semantic_switch = patch.object(settings, "DISCOVERY_SEMANTIC_ENABLED", False)
        semantic_switch.start()
        self.addCleanup(semantic_switch.stop)
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        SQLModel.metadata.create_all(self.engine)
        self.session = Session(self.engine)
        ensure_demo_posts(self.session)
        self.session.add(Trip(id="trip-own", user_id="u1", title="杭州慢行", location="杭州"))
        self.session.add(Trip(id="trip-foreign", user_id="u2", title="别人的旅行", location="厦门"))
        self.session.commit()
        app = create_app()
        def test_session():
            with Session(self.engine) as session:
                yield session
        app.dependency_overrides[get_session] = test_session
        app.dependency_overrides[get_current_user_id] = lambda: "u1"
        # No lifespan context: these tests never touch the configured runtime DB.
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        self.session.close()
        self.engine.dispose()

    def payload(self, **kwargs):
        values = dict(request_id="test-request-001", trip_id="trip-own", title="西湖边的半天",
                      destination="杭州", body="在湖边散步，坐下来休息了一会儿。", tags=["慢旅行"])
        values.update(kwargs)
        return PostInput(**values)

    def asset(self, asset_id="photo-own", user="u1", usage="upload"):
        row = FileAsset(id=asset_id, user_id=user, relative_path="/static/uploads/" + asset_id + ".jpg",
                        mime_type="image/jpeg", size_bytes=200, usage_type=usage, status="temporary")
        self.session.add(row)
        self.session.commit()
        return row

    def test_demo_is_labeled_and_seed_is_idempotent(self):
        self.assertEqual(ensure_demo_posts(self.session), 0)
        self.assertEqual(len(demo_posts()), 50)
        self.assertEqual(len({row.title for row in demo_posts()}), 50)
        feed = service.feed(self.session, "u1")
        self.assertEqual(feed["total"], 50)
        self.assertTrue(all(item["isDemo"] and not item["saved"] for item in feed["items"]))
        self.assertNotIn("likeCount", feed["items"][0])

    def test_search_destination_plus_theme_and_no_hit(self):
        feed = service.feed(self.session, "u1", query="杭州 徒步")
        self.assertEqual([item["id"] for item in feed["items"]], ["demo_note_002"])
        self.assertEqual(service.feed(self.session, "u1", query="不存在的冷门地名zz9")["total"], 0)
        self.assertGreater(service.feed(self.session, "u1", query="citywalk")["total"], 0)

    def test_stable_pages_do_not_repeat(self):
        pages = [service.feed(self.session, "u1", offset=offset, limit=20) for offset in (0, 20, 40)]
        ids = [item["id"] for page in pages for item in page["items"]]
        self.assertEqual(len(ids), 50)
        self.assertEqual(len(set(ids)), 50)
        self.assertIsNone(pages[-1]["nextOffset"])

    def test_short_term_search_changes_recommendations(self):
        service.record_search(self.session, "u1", "杭州 徒步")
        result = service.feed(self.session, "u1")
        self.assertEqual(result["items"][0]["id"], "demo_note_002")
        service.record_search(self.session, "u1", "厦门 海边")
        self.assertTrue(all(item["destination"] == "厦门" for item in service.feed(self.session, "u1")["items"][:3]))

    def test_old_search_expires(self):
        from app.models.discovery import DiscoveryPreference
        self.session.add(DiscoveryPreference(user_id="u1", recent_searches=[
            {"query": "杭州 徒步", "at": (utcnow() - timedelta(days=15)).isoformat()},
        ]))
        self.session.commit()
        self.assertEqual(service.feed(self.session, "u1")["profile"]["destination"], "")

    def test_save_hide_restore_are_persistent_and_idempotent(self):
        for _ in range(2):
            service.set_feedback(self.session, "u1", "demo_note_011", "save")
        self.assertEqual(len(self.session.exec(select(DiscoveryFeedback)).all()), 1)
        self.assertEqual(service.feed(self.session, "u1", mode="saved")["total"], 1)
        service.set_feedback(self.session, "u1", "demo_note_011", "dismiss")
        self.assertEqual(service.feed(self.session, "u1")["total"], 49)
        self.assertEqual(service.feed(self.session, "u1", mode="saved")["total"], 0)
        self.assertEqual(service.feed(self.session, "u1", mode="hidden")["items"][0]["id"], "demo_note_011")
        service.set_feedback(self.session, "u1", "demo_note_011", "restore")
        self.assertEqual(service.feed(self.session, "u1")["total"], 50)

    def test_feedback_is_user_scoped(self):
        service.set_feedback(self.session, "u1", "demo_note_011", "save")
        self.assertEqual(service.feed(self.session, "u2", mode="saved")["total"], 0)
        self.assertFalse(service.detail(self.session, "u2", "demo_note_011")["saved"])

    def test_confirmed_memory_avoids_negated_theme(self):
        positive, negative = preferences_from_text("喜欢海边，不喜欢徒步，不想自驾。更喜欢公共交通")
        self.assertIn("海边", positive)
        self.assertNotIn("徒步", positive)
        self.assertEqual(negative, {"徒步", "自驾"})
        self.session.add(UserMemory(id="mem", user_id="u1", memory_text="", memory_json={
            "schema_version": 3, "enabled": True, "items": [
                {"text": "不喜欢徒步", "state": "saved", "enabled": True},
                {"text": "喜欢海边", "state": "pending", "enabled": True},
            ],
        }))
        self.session.commit()
        feed = service.feed(self.session, "u1", limit=50)
        self.assertTrue(all("徒步" not in item["tags"] for item in feed["items"]))
        current_search = service.feed(self.session, "u1", query="杭州 徒步")
        self.assertEqual(current_search["items"][0]["id"], "demo_note_002")
        self.assertNotIn("海边", feed["profile"]["memoryTags"])
        service.set_feedback(self.session, "u1", "demo_note_002", "save")
        self.assertEqual(service.feed(self.session, "u1", mode="saved")["total"], 1)

    def test_disabled_memory_does_not_influence_history(self):
        self.session.add(UserMemory(id="mem", user_id="u1", memory_text="", memory_json={
            "schema_version": 3, "enabled": False,
            "items": [{"text": "喜欢海边", "state": "saved", "enabled": True}],
        }))
        self.session.commit()
        feed = service.feed(self.session, "u1")
        self.assertFalse(feed["profile"]["historyEnabled"])
        self.assertEqual(feed["profile"]["memoryTags"], [])

    def test_future_plan_is_not_a_visit(self):
        self.session.add(Plan(id="future-plan", user_id="u1", trip_id="trip-own", location="杭州",
                              start_date=(utcnow().date() + timedelta(days=5)).isoformat(),
                              date_label="未来", content="", itinerary_data={}))
        self.session.commit()
        profile = service.feed(self.session, "u1")["profile"]
        self.assertEqual(profile["visitedCount"], 0)
        self.assertEqual(profile["plannedDestinations"], ["杭州"])

    def test_persona_counts_independent_trips_and_ignores_invalid_numbers(self):
        for index in range(4):
            self.session.add(Report(id=f"report-{index}", user_id="u1", trip_id="trip-own",
                location="杭州", date_label="", cover_image="", personality_summary="旅行主题", content="",
                profile_data={"confidence": .8, "persona_vector": {"dims": ["nature"], "values": [.9]}}))
        self.session.commit()
        reader, profile = service.reader_context(self.session, "u1", demo_posts(), {})
        self.assertEqual(profile["personaTripCount"], 1)
        self.assertLessEqual(reader.persona_confidence, .2)

    def test_intent_beats_opposite_low_confidence_persona(self):
        notes = [service.as_note(row) for row in demo_posts()]
        reader = Reader(destination="厦门", tags={"海边"}, persona={"人文": 1, "城市漫步": 1}, persona_confidence=.05)
        ranked = rank_notes(notes, reader)
        self.assertEqual(ranked[0].note.destination, "厦门")
        self.assertIn("海边", ranked[0].note.tags)

    def test_publish_only_selected_content_and_keeps_asset_references(self):
        asset = self.asset()
        first = service.publish(self.session, "u1", self.payload(photo_asset_ids=[asset.id]))
        self.assertEqual(first["photos"], [asset.relative_path])
        self.assertEqual(first["attachments"], {"reports": [], "postcards": [], "plans": []})
        ref = self.session.exec(select(FileAssetReference).where(FileAssetReference.owner_id == first["id"])).one()
        self.assertEqual(ref.owner_type, "discovery_post")
        self.assertEqual(service.publish(self.session, "u1", self.payload(photo_asset_ids=[asset.id]))["id"], first["id"])
        service.withdraw(self.session, "u1", first["id"])
        self.assertIsNotNone(self.session.get(FileAssetReference, ref.id))
        self.assertIsNotNone(self.session.get(Trip, "trip-own"))

    def test_foreign_trip_and_foreign_photo_cannot_be_published(self):
        with self.assertRaises(Exception):
            service.publish(self.session, "u1", self.payload(trip_id="trip-foreign"))
        foreign = self.asset("photo-foreign", "u2")
        with self.assertRaises(InvalidParamError):
            service.publish(self.session, "u1", self.payload(photo_asset_ids=[foreign.id]))

    def test_generated_image_cannot_be_disguised_as_upload(self):
        generated = self.asset("generated", usage="generated_postcard")
        with self.assertRaises(InvalidParamError):
            service.publish(self.session, "u1", self.payload(photo_asset_ids=[generated.id]))

    def test_attachment_must_belong_to_selected_trip(self):
        self.session.add(Report(id="other-report", user_id="u1", trip_id=None, location="西安",
            date_label="", cover_image="", personality_summary="其他旅程", content="报告"))
        self.session.commit()
        with self.assertRaises(InvalidParamError):
            service.publish(self.session, "u1", self.payload(report_ids=["other-report"]))

    def test_itinerary_snapshot_excludes_booking_memory_and_dates(self):
        plan = Plan(id="plan", user_id="u1", trip_id="trip-own", location="杭州", date_label="私有日期",
            content="private", itinerary_data={
                "bookings": [{"ticket_number": "PRIVATE"}], "memory_context": {"secret": "PRIVATE"},
                "itinerary": [{"date": "2030-01-01", "title": "湖岸", "schedules": [
                    {"activity": "湖边散步", "place_name": "西湖", "private": "PRIVATE"},
                ]}],
            })
        self.session.add(plan)
        self.session.commit()
        post = service.publish(self.session, "u1", self.payload(plan_ids=["plan"]))
        snapshot = post["attachments"]["plans"][0]
        self.assertEqual(snapshot["days"][0]["stops"], ["湖边散步"])
        self.assertNotIn("PRIVATE", json.dumps(snapshot))
        self.assertNotIn("2030-01-01", json.dumps(snapshot))

    def test_postcard_snapshot_has_own_image_reference(self):
        image = self.asset("card-image", usage="generated_postcard")
        self.session.add(PostcardGroup(id="group", user_id="u1", trip_id="trip-own", location="杭州", date_label="", cover_image=image.relative_path))
        self.session.commit()
        self.session.add(Postcard(id="card", user_id="u1", group_id="group", title="西湖", image_url=image.relative_path))
        self.session.commit()
        post = service.publish(self.session, "u1", self.payload(postcard_ids=["card"]))
        self.assertEqual(post["photos"], [image.relative_path])
        self.assertEqual(self.session.get(FileAsset, image.id).ref_count, 1)

    def test_cannot_withdraw_demo_or_someone_elses_post(self):
        with self.assertRaises(InvalidParamError):
            service.withdraw(self.session, "u1", "demo_note_001")

    def test_ai_output_requires_evidence_and_does_not_publish(self):
        raw = json.dumps({"title": "湖边慢慢走", "body": "我在湖边散步，不喜欢徒步。",
            "tags": [{"tag": "徒步", "evidence": "徒步"}, {"tag": "海边", "evidence": "我看到了海"}]}, ensure_ascii=False)
        with patch("app.ai.clients.ark_chat_client.chat_messages", return_value=SimpleNamespace(content=raw)) as model:
            result = service.assist(AssistInput(body="我在湖边散步，不喜欢徒步。"))
        self.assertEqual(model.call_args.kwargs["max_attempts"], 1)
        self.assertFalse(model.call_args.kwargs["thinking_enabled"])
        self.assertEqual(result["source"], "ai")
        self.assertEqual(result["tags"], [])
        self.assertEqual(service.feed(self.session, "u1", mode="mine")["total"], 0)

    def test_ai_failure_keeps_original_words(self):
        with patch("app.ai.clients.ark_chat_client.chat_messages", side_effect=RuntimeError("offline")):
            result = service.assist(AssistInput(body="我喜欢海边，慢节奏。"))
        self.assertEqual(result["source"], "rules")
        self.assertEqual(result["body"], "我喜欢海边，慢节奏。")

    def test_http_envelope_validation_and_feed(self):
        payload = self.client.get("/api/discovery/feed?q=杭州").json()
        self.assertEqual(payload["code"], 0)
        self.assertEqual(payload["data"]["total"], 5)
        self.assertNotEqual(self.client.get("/api/discovery/feed?limit=1000").json()["code"], 0)
        self.assertNotEqual(self.client.post("/api/discovery/posts", json={"title": "oops"}).json()["code"], 0)
        self.assertEqual(self.client.post("/api/discovery/searches", json={"query": "厦门 海边"}).json()["code"], 0)
        self.assertEqual(self.client.get("/api/discovery/feed").json()["data"]["items"][0]["destination"], "厦门")


if __name__ == "__main__":
    unittest.main()
