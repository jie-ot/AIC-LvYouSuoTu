from __future__ import annotations

import unittest

from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.ai.schemas import PhotoAnalysisItem, PhotoAnalysisResult
from app.ai.memory import context_builder
from app.core.exceptions import InvalidParamError
from app.models import tables  # noqa: F401
from app.models.plan import Plan
from app.models.postcard import Postcard
from app.models.postcard_group import PostcardGroup
from app.models.report import Report
from app.services import generation_service, memory_service, profile_engine, trip_service
from app.services.memory_display_adapter import MemoryDisplayAdapter


class TripAndMemoryV3Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        SQLModel.metadata.create_all(self.engine)
        self.session = Session(self.engine)

    def tearDown(self) -> None:
        self.session.close()
        self.engine.dispose()

    def test_only_explicit_actionable_requirement_becomes_suggestion(self) -> None:
        abstract = generation_service._propose_memory_update(
            location="杭州",
            analysis=None,
            requirements="喜欢旅行中的光影",
        )
        self.assertEqual(abstract.add_preferences, [])

        concrete = "酒店要安静，步行 10 分钟内到地铁"
        proposal = generation_service._propose_memory_update(
            location="杭州",
            analysis=None,
            requirements=concrete,
        )
        self.assertEqual(proposal.add_preferences, ["酒店要安静", "步行 10 分钟内到地铁"])

        memory = memory_service.merge_memory_update(
            self.session,
            user_id="u-memory",
            add_preferences=proposal.add_preferences,
            weaken_preferences=[],
            evidence_summary="",
            confidence=1,
            source_type="explicit_requirement",
            source_id="op-1",
            trip_fingerprint="trip-1",
        )
        shown = MemoryDisplayAdapter().to_display(memory)
        self.assertEqual([item.state for item in shown.memories], ["candidate", "candidate"])
        self.assertEqual(memory_service.build_memory_summary(memory), "")

        confirmed = memory_service.patch_memory_item(
            self.session,
            user_id="u-memory",
            item_id=shown.memories[0].id,
            confirm=True,
            expected_version=memory.version,
        )
        self.assertIn("酒店要安静", memory_service.build_memory_summary(confirmed))
        self.assertNotIn("步行 10 分钟内到地铁", memory_service.build_memory_summary(confirmed))

    def test_photo_inference_is_ignored_and_legacy_abstract_text_is_archived(self) -> None:
        memory = memory_service.get_or_create_current_memory(self.session, "u-legacy")
        version = memory.version
        ignored = memory_service.merge_memory_update(
            self.session,
            user_id="u-legacy",
            add_preferences=["偏好用照片记录旅行中的光线与空间"],
            weaken_preferences=[],
            evidence_summary="",
            confidence=0.9,
            source_type="generate",
            source_id="old-op",
            trip_fingerprint="old-trip",
        )
        self.assertEqual(ignored.version, version)
        self.assertEqual(ignored.memory_json["items"], [])

        ignored.memory_json = {
            "schema_version": 2,
            "preferences": [
                {
                    "summary": "偏好用照片记录旅行中的光线与空间",
                    "origin": "manual",
                    "state": "active",
                },
                {
                    "summary": "经常拍摄夜景",
                    "origin": "inferred",
                    "state": "active",
                },
            ],
        }
        self.session.add(ignored)
        self.session.flush()
        upgraded = memory_service.get_or_create_current_memory(self.session, "u-legacy")
        shown = MemoryDisplayAdapter().to_display(upgraded)
        self.assertTrue(shown.is_empty)
        self.assertEqual(shown.legacy_count, 2)
        self.assertEqual(memory_service.build_memory_summary(upgraded), "")

    def test_manual_category_is_kept_when_text_mentions_another_category(self) -> None:
        memory = memory_service.add_memory_item(
            self.session,
            user_id="u-category",
            text="酒店要安静，步行 10 分钟内到地铁",
            category="hotel",
        )
        item = MemoryDisplayAdapter().to_display(memory).memories[0]
        self.assertEqual(item.category, "hotel")
        self.assertEqual(item.title, "住宿")

    def test_trip_summary_groups_all_three_artifact_types(self) -> None:
        trip = trip_service.create_in_session(
            self.session,
            user_id="u-trip",
            title="杭州周末",
            location="杭州",
        )
        self.session.add(Plan(
            id="plan-1",
            user_id="u-trip",
            trip_id=trip.id,
            location="杭州",
            date_label="日期待定",
            content="",
            itinerary_data={
                "trip_info": {
                    "destination": "杭州",
                    "start_date": "",
                    "end_date": "",
                    "date_label": "日期待定",
                },
                "preparations": [],
                "bookings": [],
                "food_recommendations": [],
                "itinerary": [],
            },
        ))
        group = PostcardGroup(
            id="group-1",
            user_id="u-trip",
            trip_id=trip.id,
            location="杭州",
            date_label="日期待定",
            cover_image="/cover.jpg",
        )
        self.session.add(group)
        self.session.add(Postcard(
            id="postcard-1",
            user_id="u-trip",
            group_id=group.id,
            title="西湖",
            image_url="/postcard.jpg",
        ))
        self.session.add(Report(
            id="report-1",
            user_id="u-trip",
            trip_id=trip.id,
            location="杭州",
            date_label="日期待定",
            cover_image="/cover.jpg",
            personality_summary="西湖",
            content="照片印象｜湖面与远山",
        ))
        self.session.commit()

        summary = trip_service.list_trips(self.session, "u-trip")[0]
        self.assertEqual((summary.plan_count, summary.postcard_count, summary.report_count), (1, 1, 1))
        detail = trip_service.get_trip(self.session, "u-trip", trip.id)
        self.assertEqual(len(detail.plans), 1)
        self.assertEqual(len(detail.postcard_groups[0].postcards), 1)
        self.assertEqual(len(detail.reports), 1)

    def test_report_copy_stays_concrete(self) -> None:
        analysis = PhotoAnalysisResult(
            overall_location="杭州",
            photos=[PhotoAnalysisItem(
                asset_id="asset-1",
                scene_summary="湖边步道与远山",
                observed_facts=["湖边步道", "远山"],
                scene_tags=["nature"],
                suitability="good",
                analysis_confidence=0.9,
            )],
        )
        report = profile_engine.build_profile(
            analysis,
            requirements="酒店要安静",
            memory_json={"schema_version": 3, "items": []},
        )
        visible_text = " ".join([
            report.content,
            report.profile_data.summary or "",
            report.profile_data.scope_note,
            *(item.reason for item in report.profile_data.next_trip_experiments),
        ])
        for unwanted in ("画像", "取景签名", "置信度", "待验证", "喜欢光影"):
            self.assertNotIn(unwanted, visible_text)
        self.assertIn("本次旅程人格", visible_text)
        self.assertIn("湖边步道", visible_text)

    def test_saved_memory_is_not_injected_into_photo_creation(self) -> None:
        analysis = PhotoAnalysisResult(
            overall_location="杭州",
            photos=[PhotoAnalysisItem(
                asset_id="asset-1",
                scene_summary="湖边步道",
                observed_facts=["湖边步道"],
                scene_tags=["nature"],
                suitability="good",
                analysis_confidence=0.9,
            )],
        )
        text = context_builder.build_postcard_selection_user_text(
            analysis=analysis,
            requirements="保留横版",
            memory_summary="酒店要安静",
        )
        self.assertIn("保留横版", text)
        self.assertNotIn("酒店要安静", text)
        self.assertNotIn("旅行记忆", text)

    def test_trip_cover_falls_back_to_a_remaining_artifact(self) -> None:
        trip = trip_service.create_in_session(
            self.session,
            user_id="u-cover",
            title="杭州",
            location="杭州",
            cover_image="/removed.jpg",
        )
        removed = PostcardGroup(
            id="group-removed",
            user_id="u-cover",
            trip_id=trip.id,
            location="杭州",
            date_label="日期待定",
            cover_image="/removed.jpg",
        )
        remaining = Report(
            id="report-remaining",
            user_id="u-cover",
            trip_id=trip.id,
            location="杭州",
            date_label="日期待定",
            cover_image="/remaining.jpg",
            personality_summary="",
            content="",
        )
        self.session.add(removed)
        self.session.add(remaining)
        self.session.flush()
        self.session.delete(removed)
        self.session.flush()

        trip_service.refresh_cover(self.session, "u-cover", trip.id)
        self.assertEqual(trip.cover_image, "/remaining.jpg")

        self.session.delete(remaining)
        self.session.flush()
        trip_service.refresh_cover(self.session, "u-cover", trip.id)
        self.assertIsNone(trip.cover_image)

    def test_only_empty_trip_can_be_deleted(self) -> None:
        empty = trip_service.create_in_session(
            self.session,
            user_id="u-delete",
            title="空旅行",
        )
        empty_id = empty.id
        trip_service.delete_empty_trip(self.session, "u-delete", empty_id)
        self.session.flush()
        self.assertIsNone(self.session.get(type(empty), empty_id))

        trip = trip_service.create_in_session(
            self.session,
            user_id="u-delete",
            title="有内容的旅行",
        )
        self.session.add(Report(
            id="report-delete-guard",
            user_id="u-delete",
            trip_id=trip.id,
            location="杭州",
            date_label="日期待定",
            cover_image="/cover.jpg",
            personality_summary="",
            content="",
        ))
        self.session.flush()
        with self.assertRaises(InvalidParamError):
            trip_service.delete_empty_trip(self.session, "u-delete", trip.id)


if __name__ == "__main__":
    unittest.main()
