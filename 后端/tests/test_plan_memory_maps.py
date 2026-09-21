"""Classification, plan-memory extraction, display emptiness, and daily maps."""

from __future__ import annotations

import unittest

from app.models.itinerary import DailyItinerary, ItineraryData, Schedule, TripInfo
from app.models.user_memory import UserMemory
from app.services.daily_map_service import _candidate_groups
from app.services.memory_display_adapter import MemoryDisplayAdapter
from app.services import plan_service
from app.services.schedule_kind import classify_schedule


def _schedule(**kwargs) -> Schedule:
    payload = {
        "id": "s1",
        "time_period": "上午",
        "activity": "游览",
    }
    payload.update(kwargs)
    return Schedule(**payload)


def _verified(**kwargs) -> Schedule:
    payload = {
        "fact_status": "verified",
        "fact_refs": ["fact_1"],
        "location": "116.397128,39.916527",
    }
    payload.update(kwargs)
    return _schedule(**payload)


def _trip() -> ItineraryData:
    return ItineraryData(
        trip_info=TripInfo(
            destination="北京、承德",
            start_date="2026-08-20",
            end_date="2026-08-24",
            date_label="2026.8.20 - 2026.8.24",
        ),
        preparations=[],
        bookings=[],
        food_recommendations=["推荐北京烤鸭"],
        itinerary=[],
    )


class ScheduleKindTests(unittest.TestCase):
    def test_walking_street_is_attraction(self) -> None:
        schedule = _schedule(place_name="前门大街", activity="逛步行街", tags=["街区"])
        self.assertEqual(classify_schedule(schedule), "attraction")

    def test_airport_is_transport(self) -> None:
        schedule = _schedule(place_name="首都机场", activity="乘机返回武汉", tags=["大交通"])
        self.assertEqual(classify_schedule(schedule), "transport")

    def test_restaurant_is_dining(self) -> None:
        schedule = _schedule(place_name="全聚德", activity="品尝烤鸭", tags=["美食"])
        self.assertEqual(classify_schedule(schedule), "dining")

    def test_hotel_checkout_with_airport_in_activity_stays_hotel(self) -> None:
        schedule = _schedule(
            place_name="承德山庄酒店",
            activity="退房后前往机场",
            tags=["住宿"],
        )
        airport_fact = {
            "typecode": "150104",
            "category": "交通设施;机场",
            "name": "首都机场",
        }
        self.assertEqual(classify_schedule(schedule, airport_fact), "hotel")


class PlanMemoryExtractionTests(unittest.TestCase):
    def test_ai_itinerary_has_no_memory_extraction_hook(self) -> None:
        self.assertFalse(hasattr(plan_service, "_memory_preferences_from_itinerary"))
        self.assertFalse(hasattr(plan_service, "_merge_memory"))


class MemoryDisplayTests(unittest.TestCase):
    def test_planning_preferences_alone_are_not_empty(self) -> None:
        memory = UserMemory(
            id="mem_1",
            user_id="u1",
            memory_text="给规划填写的特别偏好\n- 交通偏好：更愿意高铁",
            memory_json={
                "preferences": [],
                "planning_preferences": {
                    "transport": "更愿意高铁",
                    "hotel": "",
                    "attractions": "",
                    "food": "",
                    "pace": "",
                    "other": "",
                },
            },
        )
        display = MemoryDisplayAdapter().to_display(memory)
        self.assertFalse(display.is_empty)
        self.assertEqual(display.memories, [])
        self.assertNotIn("高铁", display.overview_content or "")

    def test_overview_reads_display_overview_not_memory_text(self) -> None:
        memory = UserMemory(
            id="mem_2",
            user_id="u1",
            memory_text="给规划填写的特别偏好\n- 餐饮偏好：不要辣",
            memory_json={
                "preferences": [],
                "planning_preferences": {
                    "transport": "",
                    "hotel": "",
                    "attractions": "",
                    "food": "不要辣",
                    "pace": "",
                    "other": "",
                },
                "display_overview": {
                    "title": "旅行记忆概述",
                    "content": "手写概述保持不变",
                },
            },
        )
        display = MemoryDisplayAdapter().to_display(memory)
        self.assertEqual(display.overview_content, "手写概述保持不变")
        self.assertNotIn("不要辣", display.overview_content or "")


class DailyMapProjectionTests(unittest.TestCase):
    def test_single_scenic_day_uses_carried_hotel(self) -> None:
        data = _trip()
        hotel = _verified(
            id="h1",
            activity="入住承德山庄酒店",
            place_name="承德山庄酒店",
            tags=["住宿"],
            location="117.938012,40.986441",
            fact_refs=["hotel_cd"],
        )
        scenic = _verified(
            id="a1",
            activity="游览避暑山庄",
            place_name="避暑山庄",
            tags=["景区"],
            location="117.935201,40.992118",
            fact_refs=["scenic_cd"],
        )
        checkin_day = DailyItinerary(
            id="d1",
            date="2026-08-22",
            title="抵达承德",
            schedules=[hotel],
        )
        scenic_day = DailyItinerary(
            id="d2",
            date="2026-08-23",
            title="避暑山庄",
            schedules=[scenic],
        )
        facts = {
            "hotel_cd": {"city_name": "承德", "typecode": "100100", "category": "住宿服务"},
            "scenic_cd": {"city_name": "承德", "typecode": "110200", "category": "风景名胜"},
        }
        groups, overnight, city = _candidate_groups(
            checkin_day,
            data,
            facts=facts,
            overnight_hotel=None,
            overnight_city="承德",
        )
        self.assertEqual(groups, {})
        self.assertIsNotNone(overnight)
        groups, _, _ = _candidate_groups(
            scenic_day,
            data,
            facts=facts,
            overnight_hotel=overnight,
            overnight_city=city,
        )
        points = next(iter(groups.values()))
        names = [point.name for point in points]
        self.assertGreaterEqual(len(points), 2)
        self.assertIn("承德山庄酒店", names)
        self.assertIn("避暑山庄", names)

    def test_return_day_without_attractions_has_no_map(self) -> None:
        data = _trip()
        day = DailyItinerary(
            id="d5",
            date="2026-08-24",
            title="返程武汉",
            schedules=[
                _verified(
                    id="h2",
                    activity="退房承德山庄酒店",
                    place_name="承德山庄酒店",
                    tags=["住宿"],
                    location="117.938012,40.986441",
                    fact_refs=["hotel_cd"],
                ),
                _verified(
                    id="t1",
                    activity="乘机返回武汉",
                    place_name="首都机场",
                    tags=["大交通"],
                    location="116.584473,40.080111",
                    fact_refs=["airport"],
                ),
            ],
        )
        groups, _, _ = _candidate_groups(
            day,
            data,
            facts={
                "hotel_cd": {"city_name": "承德", "typecode": "100100"},
                "airport": {"city_name": "北京", "typecode": "150104", "category": "交通设施"},
            },
            overnight_hotel=None,
            overnight_city="承德",
        )
        self.assertEqual(groups, {})

    def test_does_not_invent_coordinates(self) -> None:
        data = _trip()
        day = DailyItinerary(
            id="d1",
            date="2026-08-20",
            title="北京文化日",
            schedules=[
                _schedule(
                    id="h1",
                    activity="入住北京饭店",
                    place_name="北京饭店",
                    tags=["住宿"],
                    fact_status="verified",
                    fact_refs=["hotel_bj"],
                ),
                _verified(
                    id="a1",
                    activity="参观故宫",
                    place_name="故宫博物院",
                    tags=["景区"],
                    fact_refs=["palace"],
                ),
            ],
        )
        groups, _, _ = _candidate_groups(
            day,
            data,
            facts={
                "hotel_bj": {"city_name": "北京", "typecode": "100100"},
                "palace": {"city_name": "北京", "typecode": "110200", "category": "风景名胜"},
            },
            overnight_hotel=None,
            overnight_city="北京",
        )
        self.assertEqual(groups, {})


if __name__ == "__main__":
    unittest.main()
