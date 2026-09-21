from __future__ import annotations

import unittest
from datetime import date, timedelta

from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.ai.schemas import PhotoAnalysisItem, PhotoAnalysisResult
from app.models import dto, tables  # noqa: F401
from app.models.file_asset_reference import FileAssetReference
from app.models.plan import Plan
from app.models.postcard_group import PostcardGroup
from app.services import memory_service, trip_service
from app.services.memory_display_adapter import MemoryDisplayAdapter


class TravelMemoryJourneyContextTests(unittest.TestCase):
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

    def _trip(self, trip_id: str, location: str):
        trip = trip_service.create_in_session(
            self.session,
            user_id="u",
            title=location,
            location=location,
            start_date="2026-05-01",
            end_date="2026-05-03",
            date_label="2026.5.1-2026.5.3",
        )
        trip.id = trip_id
        self.session.add(trip)
        self.session.flush()
        return trip

    def _plan(self, plan_id: str, trip_id: str, place: str) -> None:
        self.session.add(Plan(
            id=plan_id,
            user_id="u",
            trip_id=trip_id,
            location="测试城市",
            date_label="2026.5.1-2026.5.3",
            content="",
            itinerary_data={
                "trip_info": {"destination": "测试城市", "date_label": "2026.5.1-2026.5.3"},
                "preparations": [],
                "bookings": [],
                "food_recommendations": [],
                "itinerary": [{
                    "id": "day-1",
                    "date": "2026-05-01",
                    "schedules": [{
                        "id": f"schedule-{plan_id}",
                        "time_period": "上午",
                        "activity": f"参观{place}",
                        "place_name": place,
                        "map_role": "attraction",
                        "tags": ["历史", "博物馆"],
                    }],
                }],
            },
        ))

    def test_history_is_visible_and_repeated_plans_are_not_used_implicitly(self) -> None:
        first = self._trip("trip-1", "南京")
        second = self._trip("trip-2", "北京")
        self._plan("plan-1", first.id, "南京博物院")
        self._plan("plan-2", second.id, "故宫博物院")
        group = PostcardGroup(
            id="group-1",
            user_id="u",
            trip_id=first.id,
            location="南京",
            date_label="2026.5.1-2026.5.3",
            cover_image="/cover.jpg",
        )
        self.session.add(group)
        self.session.add(FileAssetReference(
            id="ref-1",
            user_id="u",
            asset_id="asset-1",
            owner_type="postcard_group",
            owner_id=group.id,
            role="source_photo",
        ))
        self.session.commit()

        memory = memory_service.get_or_create_current_memory(self.session, "u")
        display = MemoryDisplayAdapter().to_display(
            memory, session=self.session, user_id="u",
        )
        self.assertEqual(display.stats.trip_count, 2)
        self.assertEqual(display.stats.place_count, 2)
        self.assertEqual(display.stats.photo_count, 1)
        self.assertEqual(display.stats.plan_count, 2)
        self.assertEqual(len(display.footprints), 2)
        culture = next(item for item in display.patterns if item.id == "pattern_travel_type_culture")
        self.assertTrue(culture.confirmable)
        self.assertEqual(culture.support_count, 2)
        self.assertEqual(memory_service.build_memory_summary(memory), "")

        confirmed = memory_service.confirm_observed_pattern(
            self.session,
            user_id="u",
            pattern=culture,
            expected_version=memory.version,
        )
        self.assertIn("博物馆", memory_service.build_memory_summary(confirmed))

    def test_dotted_date_label_is_enough_to_mark_a_past_trip_recorded(self) -> None:
        past = date.today() - timedelta(days=2)
        trip = trip_service.create_in_session(
            self.session,
            user_id="u",
            title="旧旅行",
            location="苏州",
            start_date=None,
            end_date=None,
            date_label=f"{past.year}.{past.month}.{past.day}",
        )
        self.session.commit()
        memory = memory_service.get_or_create_current_memory(self.session, "u")
        display = MemoryDisplayAdapter().to_display(
            memory, session=self.session, user_id="u",
        )
        footprint = next(item for item in display.footprints if item.trip_id == trip.id)
        self.assertEqual(footprint.state_label, "已记录")

    def test_photo_evidence_accumulates_across_trips_before_confirmation(self) -> None:
        self._trip("trip-photo-1", "大连")
        self._trip("trip-photo-2", "三亚")
        memory_service.record_trip_observation(
            self.session,
            user_id="u",
            trip_id="trip-photo-1",
            operation_id="op-1",
            analysis=PhotoAnalysisResult(
                overall_location="大连",
                photos=[PhotoAnalysisItem(
                    asset_id="asset-1",
                    scene_summary="海岸步道",
                    observed_facts=["照片中可见海岸步道"],
                    scene_tags=["coast"],
                    suitability="good",
                )],
            ),
            photos=[dto.UploadedPhoto(
                asset_id="asset-1",
                image_url="/static/uploads/1.jpg",
                taken_at="2026-05-01T09:00:00",
                location="大连",
            )],
        )
        memory = memory_service.get_or_create_current_memory(self.session, "u")
        first_display = MemoryDisplayAdapter().to_display(
            memory, session=self.session, user_id="u",
        )
        first_pattern = next(
            item for item in first_display.patterns if item.id == "pattern_travel_type_coast"
        )
        self.assertFalse(first_pattern.confirmable)
        self.assertEqual(memory_service.build_memory_summary(memory), "")

        memory_service.record_trip_observation(
            self.session,
            user_id="u",
            trip_id="trip-photo-2",
            operation_id="op-2",
            analysis=PhotoAnalysisResult(
                overall_location="三亚",
                photos=[PhotoAnalysisItem(
                    asset_id="asset-2",
                    scene_summary="沙滩与海面",
                    observed_facts=["照片中可见沙滩与海面"],
                    scene_tags=["coast"],
                    suitability="good",
                )],
            ),
            photos=[dto.UploadedPhoto(
                asset_id="asset-2",
                image_url="/static/uploads/2.jpg",
                taken_at="2026-06-02T16:00:00",
                location="三亚",
            )],
        )
        memory = memory_service.get_or_create_current_memory(self.session, "u")
        display = MemoryDisplayAdapter().to_display(
            memory, session=self.session, user_id="u",
        )
        coast = next(item for item in display.patterns if item.id == "pattern_travel_type_coast")
        self.assertEqual(coast.source_kind, "photos")
        self.assertEqual(coast.support_count, 2)
        self.assertTrue(coast.confirmable)
        self.assertEqual(memory_service.build_memory_summary(memory), "")

    def test_photo_time_and_location_stay_factual_until_user_confirms(self) -> None:
        self._trip("trip-long-1", "厦门")
        self._trip("trip-long-2", "青岛")
        for index, trip_id in enumerate(("trip-long-1", "trip-long-2"), start=1):
            morning_id = f"asset-{index}-morning"
            evening_id = f"asset-{index}-evening"
            memory_service.record_trip_observation(
                self.session,
                user_id="u",
                trip_id=trip_id,
                operation_id=f"op-long-{index}",
                analysis=PhotoAnalysisResult(
                    overall_location="测试海滨城市",
                    photos=[
                        PhotoAnalysisItem(
                            asset_id=morning_id,
                            scene_summary="海滨步道",
                            location_guess="海滨步道",
                            observed_facts=["照片中可见海岸步道"],
                            scene_tags=["coast"],
                            suitability="good",
                        ),
                        PhotoAnalysisItem(
                            asset_id=evening_id,
                            scene_summary="港湾夜景",
                            location_guess="港湾观景区",
                            observed_facts=["照片中可见港湾灯光"],
                            scene_tags=["coast", "night"],
                            suitability="good",
                        ),
                    ],
                ),
                photos=[
                    dto.UploadedPhoto(
                        asset_id=morning_id,
                        image_url=f"/static/uploads/{morning_id}.jpg",
                        taken_at="2026-05-01T09:00:00",
                        location="24.47,118.08",
                    ),
                    dto.UploadedPhoto(
                        asset_id=evening_id,
                        image_url=f"/static/uploads/{evening_id}.jpg",
                        taken_at="2026-05-01T18:00:00",
                        location="24.48,118.10",
                    ),
                ],
            )

        memory = memory_service.get_or_create_current_memory(self.session, "u")
        display = MemoryDisplayAdapter().to_display(
            memory, session=self.session, user_id="u",
        )
        first = next(item for item in display.footprints if item.trip_id == "trip-long-1")
        self.assertIn("海滨步道", first.highlights)
        self.assertIn("同日照片最长间隔约 9 小时", first.pace_label or "")
        full_day = next(
            item for item in display.patterns if item.id == "pattern_photo_full_day"
        )
        self.assertEqual(full_day.support_count, 2)
        self.assertTrue(full_day.confirmable)
        self.assertEqual(memory_service.build_memory_summary(memory), "")


if __name__ == "__main__":
    unittest.main()
