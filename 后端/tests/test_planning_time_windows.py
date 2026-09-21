from __future__ import annotations

from unittest import TestCase

from app.ai import orchestrator
from app.models.itinerary import ItineraryData


class PlanningTimeWindowTest(TestCase):
    def test_embedded_departure_time_passes_but_vague_night_flight_fails(self) -> None:
        data = ItineraryData.model_validate(
            {
                "trip_info": {
                    "destination": "丹东、大连",
                    "start_date": "2026-08-08",
                    "end_date": "2026-08-11",
                    "date_label": "4天",
                },
                "preparations": [],
                "bookings": [],
                "food_recommendations": [],
                "itinerary": [
                    {
                        "id": "day_8",
                        "date": "2026-08-08",
                        "schedules": [
                            {
                                "id": "rail",
                                "time_period": "下午",
                                "start_time": "15:20",
                                "end_time": "20:15",
                                "activity": "取行李后乘D7758次（17:53）从丹东前往大连",
                            }
                        ],
                    },
                    {
                        "id": "day_9",
                        "date": "2026-08-09",
                        "schedules": [{"id": "a", "time_period": "上午", "activity": "游玩"}],
                    },
                    {
                        "id": "day_10",
                        "date": "2026-08-10",
                        "schedules": [{"id": "b", "time_period": "上午", "activity": "游玩"}],
                    },
                    {
                        "id": "day_11",
                        "date": "2026-08-11",
                        "schedules": [
                            {
                                "id": "flight",
                                "time_period": "下午",
                                "start_time": "13:00",
                                "end_time": "17:00",
                                "activity": "前往机场，准备搭乘夜间航班返回南京",
                            }
                        ],
                    },
                ],
            }
        )
        request = "8月8日傍晚从丹东去大连，8月11日晚上从大连返回南京。"

        problems = orchestrator._time_window_problems(data, request)

        self.assertEqual(len(problems), 1)
        self.assertEqual(
            problems[0].message,
            "2026-08-11 晚上前往南京缺少 18:00–23:59 内的独立跨城交通日程",
        )
        # Day-scoped so annotate_unresolved can surface a traveller-facing advisory
        # on any trip that states an evening/morning window, not just this fixture.
        self.assertEqual(problems[0].date, "2026-08-11")
        self.assertIsNone(problems[0].schedule_id)
        self.assertTrue(problems[0].blocking)

    def test_hao_and_hui_phrasing_is_accepted_like_ri_and_fan_hui(self) -> None:
        """Users write 「8月11号晚上回南京」 as often as 「8月11日…返回」."""
        data = ItineraryData.model_validate(
            {
                "trip_info": {
                    "destination": "乌鲁木齐",
                    "start_date": "2026-09-01",
                    "end_date": "2026-09-03",
                    "date_label": "3天",
                },
                "preparations": [],
                "bookings": [],
                "food_recommendations": [],
                "itinerary": [
                    {
                        "id": "day_3",
                        "date": "2026-09-03",
                        "schedules": [
                            {
                                "id": "flight",
                                "time_period": "上午",
                                "start_time": "08:20",
                                "end_time": "12:00",
                                "activity": "乘早班飞机回南京",
                            }
                        ],
                    }
                ],
            }
        )

        problems = orchestrator._time_window_problems(
            data, "9月1号出发，在乌鲁木齐玩到9月3号晚上回南京"
        )

        self.assertEqual(len(problems), 1)
        self.assertEqual(problems[0].date, "2026-09-03")
        self.assertIn("晚上前往南京", problems[0].message)
