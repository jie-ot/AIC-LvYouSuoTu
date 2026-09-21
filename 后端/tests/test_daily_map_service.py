from __future__ import annotations

from unittest import TestCase
from unittest.mock import patch

from app.models.itinerary import ItineraryData
from app.services import daily_map_service


def _itinerary() -> ItineraryData:
    return ItineraryData.model_validate(
        {
            "trip_info": {
                "destination": "丹东、大连",
                "start_date": "2026-08-07",
                "end_date": "2026-08-11",
                "date_label": "5天4晚",
            },
            "preparations": [],
            "bookings": [],
            "food_recommendations": [],
            "itinerary": [
                {
                    "id": "day_20260807",
                    "date": "2026-08-07",
                    "title": "丹东初见",
                    "schedules": [
                        {
                            "id": "sch_hotel",
                            "time_period": "下午",
                            "activity": "入住酒店",
                            "place_name": "丹东江景酒店",
                            "location": "124.394324,40.136111",
                            "fact_status": "verified",
                            "fact_refs": ["fact_hotel"],
                            "map_role": "hotel",
                            "map_group": "丹东市区",
                            "map_label": "江景酒店",
                        },
                        {
                            "id": "sch_bridge",
                            "time_period": "晚上",
                            "activity": "鸭绿江断桥夜游",
                            "place_name": "鸭绿江断桥",
                            "location": "124.386526,40.123614",
                            "travel_minutes": 12,
                            "transport_mode": "walking",
                            "fact_status": "verified",
                            "fact_refs": ["fact_bridge"],
                            "map_role": "attraction",
                            "map_group": "丹东市区",
                            "map_label": "鸭绿江断桥",
                        },
                        {
                            "id": "sch_bridge_inside",
                            "time_period": "晚上",
                            "activity": "断桥观景台",
                            "place_name": "鸭绿江断桥观景台",
                            "location": "124.386526,40.123614",
                            "fact_status": "verified",
                            "fact_refs": ["fact_bridge"],
                            "map_role": "attraction",
                            "map_group": "丹东市区",
                            "map_label": "鸭绿江断桥",
                        },
                        {
                            "id": "sch_station",
                            "time_period": "上午",
                            "activity": "抵达丹东站",
                            "place_name": "丹东站",
                            "location": "124.381000,40.129000",
                            "fact_status": "verified",
                            "fact_refs": ["fact_station"],
                        },
                    ],
                }
            ],
        }
    )


class DailyMapServiceTest(TestCase):
    def test_deepseek_map_filters_and_deduplicates_semantic_points(self) -> None:
        data = _itinerary()
        with patch.object(
            daily_map_service,
            "_render_cached_map",
            return_value="/static/images/daily-maps/test.png",
        ):
            result = daily_map_service.enrich_daily_maps(data, "deepseek-v4-flash")

        maps = result.itinerary[0].daily_maps
        self.assertEqual(len(maps), 1)
        self.assertEqual([point.name for point in maps[0].points], ["江景酒店", "鸭绿江断桥"])
        self.assertEqual(maps[0].status, "ready")
        self.assertEqual(maps[0].legs[0].transport_text, "步行12分钟")

    def test_verified_tags_recover_map_when_deepseek_omits_all_hints(self) -> None:
        data = _itinerary()
        day = data.itinerary[0]
        for schedule in day.schedules:
            schedule.map_role = None
            schedule.map_group = None
            schedule.map_label = None
        day.schedules[0].tags = ["住宿"]
        day.schedules[1].tags = ["历史文化", "边境风光"]
        day.schedules[2].tags = ["美食", "夜景"]
        day.schedules[3].tags = ["大交通", "换乘"]

        with patch.object(
            daily_map_service,
            "_render_cached_map",
            return_value="/static/images/daily-maps/fallback.png",
        ):
            result = daily_map_service.enrich_daily_maps(data, "deepseek-v4-pro")

        daily_map = result.itinerary[0].daily_maps[0]
        self.assertEqual(daily_map.title, "丹东初见")
        self.assertEqual(
            [(point.name, point.kind) for point in daily_map.points],
            [("丹东江景酒店", "hotel"), ("鸭绿江断桥", "attraction")],
        )

    def test_non_deepseek_model_never_exposes_daily_maps(self) -> None:
        data = _itinerary()
        data.itinerary[0].daily_maps = [
            {
                "id": "map_injected",
                "title": "不应显示",
                "points": [],
                "legs": [],
            }
        ]

        result = daily_map_service.enrich_daily_maps(data, "unsupported-model")

        self.assertEqual(result.itinerary[0].daily_maps, [])

    def test_static_map_failure_keeps_text_fallback(self) -> None:
        data = _itinerary()
        with patch.object(daily_map_service, "_render_cached_map", return_value=None):
            result = daily_map_service.enrich_daily_maps(data, "deepseek-v4-pro")

        daily_map = result.itinerary[0].daily_maps[0]
        self.assertEqual(daily_map.status, "unavailable")
        self.assertIsNone(daily_map.image_url)
        self.assertEqual(len(daily_map.points), 2)
        self.assertEqual(len(daily_map.legs), 1)
