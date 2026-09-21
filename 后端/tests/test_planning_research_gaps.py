from __future__ import annotations

from datetime import date, timedelta
from unittest import TestCase
from unittest.mock import patch

from app.ai import orchestrator
from app.services import travel_fact_service


def _scope(destinations: list[str]) -> dict:
    return {
        "origin": "南京",
        "destinations": destinations,
        "startDate": "2026-08-09",
        "endDate": "2026-08-14",
        "needsTransport": True,
        "needsHotel": True,
        "interests": ["自然风光"],
        "uncertainties": [],
    }


def _flight_fact(index: int, dep: str, arr: str, day: str) -> dict:
    return {
        "fact_id": f"fact_flight_{index}",
        "tool": "searchFlightItineraries",
        "status": "ok",
        "arguments": {"depCityCode": dep, "arrCityCode": arr, "depDate": day},
        "flight_no": f"XX{index:04d}",
    }


def _hotel_fact(index: int, city: str) -> dict:
    return {
        "fact_id": f"fact_poi_search_{index}",
        "tool": "amap_poi_search",
        "status": "ok",
        "arguments": {"keyword": "酒店", "city": city},
        "name": f"{city}某连锁酒店",
        "city_name": city,
    }


def _route_fact(index: int, origin: str, destination: str) -> dict:
    return {
        "fact_id": f"fact_route_{index}",
        "tool": "amap_route",
        "status": "ok",
        "arguments": {"origin": origin, "destination": destination, "mode": "driving"},
        "origin": origin,
        "destination": destination,
        "distance_km": 12.0,
        "duration_minutes": 30,
    }


class CriticalResearchGapTest(TestCase):
    def test_two_rounds_of_the_old_fast_path_still_report_gaps(self) -> None:
        """The 北疆 run's fact set must not be treated as research-complete."""
        registry = {}
        for index, (dep, arr, day) in enumerate(
            [
                ("NKG", "URC", "2026-08-09"),
                ("URC", "NKG", "2026-08-14"),
                ("URC", "KJI", "2026-08-11"),
                ("KJI", "URC", "2026-08-13"),
            ]
        ):
            fact = _flight_fact(index, dep, arr, day)
            registry[fact["fact_id"]] = fact
        hotel = _hotel_fact(90, "乌鲁木齐")
        registry[hotel["fact_id"]] = hotel
        for index, (origin, destination) in enumerate(
            [
                ("乌鲁木齐丽海商旅酒店", "天山天池风景区"),
                ("乌鲁木齐丽海商旅酒店", "新疆国际大巴扎"),
                ("乌鲁木齐丽海商旅酒店", "乌鲁木齐地窝堡国际机场"),
            ],
            start=50,
        ):
            fact = _route_fact(index, origin, destination)
            registry[fact["fact_id"]] = fact

        gaps = orchestrator._critical_research_gaps(
            scope=_scope(["乌鲁木齐", "喀纳斯（布尔津）", "禾木"]),
            remaining_queries=[],
            fact_registry=registry,
        )

        self.assertTrue(any("过夜城市还没有具体酒店候选" in gap for gap in gaps), gaps)
        self.assertTrue(any("关键路线覆盖不足" in gap for gap in gaps), gaps)

    def test_full_coverage_reports_no_gaps(self) -> None:
        registry = {}
        for index, (dep, arr, day) in enumerate(
            [
                ("NKG", "URC", "2026-08-09"),
                ("URC", "KJI", "2026-08-11"),
                ("KJI", "URC", "2026-08-13"),
            ]
        ):
            fact = _flight_fact(index, dep, arr, day)
            registry[fact["fact_id"]] = fact
        for index, city in enumerate(["乌鲁木齐", "布尔津"], start=90):
            fact = _hotel_fact(index, city)
            registry[fact["fact_id"]] = fact
        for index, (origin, destination) in enumerate(
            [
                ("乌鲁木齐某连锁酒店", "乌鲁木齐地窝堡国际机场"),
                ("乌鲁木齐某连锁酒店", "天山天池风景区"),
                ("布尔津某连锁酒店", "布尔津喀纳斯机场"),
                ("布尔津某连锁酒店", "喀纳斯湖景区"),
            ],
            start=50,
        ):
            fact = _route_fact(index, origin, destination)
            registry[fact["fact_id"]] = fact

        gaps = orchestrator._critical_research_gaps(
            scope=_scope(["乌鲁木齐", "布尔津"]),
            remaining_queries=[],
            fact_registry=registry,
        )

        self.assertEqual(gaps, [])

    def test_missing_hub_connection_is_reported(self) -> None:
        registry = {}
        fact = _flight_fact(0, "NKG", "URC", "2026-08-09")
        registry[fact["fact_id"]] = fact
        fact = _flight_fact(1, "URC", "NKG", "2026-08-14")
        registry[fact["fact_id"]] = fact
        hotel = _hotel_fact(90, "乌鲁木齐")
        registry[hotel["fact_id"]] = hotel
        for index, (origin, destination) in enumerate(
            [
                ("乌鲁木齐某连锁酒店", "天山天池风景区"),
                ("乌鲁木齐某连锁酒店", "新疆国际大巴扎"),
            ],
            start=50,
        ):
            fact = _route_fact(index, origin, destination)
            registry[fact["fact_id"]] = fact

        gaps = orchestrator._critical_research_gaps(
            scope=_scope(["乌鲁木齐"]),
            remaining_queries=[],
            fact_registry=registry,
        )

        self.assertTrue(
            any("机场/车站之间的接驳路线" in gap for gap in gaps), gaps
        )

    def test_city_alias_matches_parenthesised_destination(self) -> None:
        registry = {}
        hotel = _hotel_fact(90, "布尔津县")
        registry[hotel["fact_id"]] = hotel

        self.assertTrue(
            orchestrator._has_hotel_fact_for_city("喀纳斯（布尔津）", registry)
        )
        self.assertFalse(orchestrator._has_hotel_fact_for_city("乌鲁木齐", registry))


class WeatherForecastHorizonTest(TestCase):
    def test_dates_beyond_the_horizon_skip_the_provider_call(self) -> None:
        far_start = (date.today() + timedelta(days=10)).isoformat()
        far_end = (date.today() + timedelta(days=15)).isoformat()
        args = travel_fact_service.tool_specs.WeatherRangeArgs.model_validate(
            {"city": "布尔津", "startDate": far_start, "endDate": far_end}
        )

        with (
            patch.object(travel_fact_service.amap_provider, "weather_range") as fetch,
            patch.object(travel_fact_service, "_persist_log"),
        ):
            result = travel_fact_service._exec_amap_weather_range(
                "user", "req", "planning", args
            )

        fetch.assert_not_called()
        self.assertEqual(result["status"], "out_of_forecast_horizon")
        self.assertEqual(result["days"], [])
        self.assertIn("超过高德", result["note"])
        self.assertFalse(result["retryable"])

    def test_near_dates_still_query_the_provider(self) -> None:
        today = date.today().isoformat()
        args = travel_fact_service.tool_specs.WeatherRangeArgs.model_validate(
            {"city": "乌鲁木齐", "startDate": today, "endDate": today}
        )

        with (
            patch.object(
                travel_fact_service.amap_provider, "is_available", return_value=True
            ),
            patch.object(
                travel_fact_service.amap_provider,
                "resolve_city_adcode",
                return_value="650100",
            ),
            patch.object(
                travel_fact_service.amap_provider, "weather_range", return_value=[]
            ) as fetch,
            patch.object(travel_fact_service, "_persist_log"),
        ):
            result = travel_fact_service._exec_amap_weather_range(
                "user", "req", "planning", args
            )

        fetch.assert_called_once()
        self.assertNotEqual(result["status"], "out_of_forecast_horizon")
