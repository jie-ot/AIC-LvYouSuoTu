from __future__ import annotations

from unittest import TestCase

from app.core.exceptions import InvalidParamError
from app.models.itinerary import ItineraryData
from app.services import itinerary_validation_service


class ItineraryValidationTest(TestCase):
    def test_rejects_overlapping_daily_schedules(self) -> None:
        data = ItineraryData.model_validate(
            {
                "trip_info": {
                    "destination": "大连",
                    "start_date": "2026-08-11",
                    "end_date": "2026-08-11",
                    "date_label": "1天",
                },
                "preparations": [],
                "bookings": [],
                "food_recommendations": [],
                "itinerary": [
                    {
                        "id": "day_1",
                        "date": "2026-08-11",
                        "schedules": [
                            {
                                "id": "train",
                                "time_period": "上午",
                                "start_time": "08:49",
                                "end_time": "17:40",
                                "activity": "乘高铁",
                            },
                            {
                                "id": "walk",
                                "time_period": "上午",
                                "start_time": "09:00",
                                "end_time": "11:00",
                                "activity": "城市漫步",
                            },
                        ],
                    }
                ],
            }
        )

        with self.assertRaisesRegex(InvalidParamError, "时间不得重叠"):
            itinerary_validation_service.validate_itinerary(data)
