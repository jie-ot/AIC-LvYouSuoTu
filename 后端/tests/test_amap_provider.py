from __future__ import annotations

from datetime import date, timedelta
from threading import Barrier, Lock
from unittest import TestCase
from unittest.mock import MagicMock, Mock, patch

from pydantic import ValidationError

from app.ai import orchestrator
from app.ai.tools import amap_provider, tool_specs


class AmapProviderTest(TestCase):
    def test_get_retries_429_but_not_non_retryable_4xx(self) -> None:
        limited = Mock(status_code=429)
        success = Mock(status_code=200)
        success.json.return_value = {"status": "1", "pois": []}
        client = MagicMock()
        client.__enter__.return_value.get.side_effect = [limited, success]

        with (
            patch.object(amap_provider.settings, "TOOL_MAX_RETRY", 1),
            patch.object(amap_provider.httpx, "Client", return_value=client),
            patch.object(amap_provider, "_throttle_amap_qps"),
            patch.object(amap_provider.time, "sleep"),
        ):
            result = amap_provider._get("/test", {"city": "苏州"})

        self.assertEqual(result, {"status": "1", "pois": []})
        self.assertEqual(client.__enter__.return_value.get.call_count, 2)

        denied = Mock(status_code=401)
        client = MagicMock()
        client.__enter__.return_value.get.return_value = denied
        with (
            patch.object(amap_provider.settings, "TOOL_MAX_RETRY", 2),
            patch.object(amap_provider.httpx, "Client", return_value=client),
            patch.object(amap_provider, "_throttle_amap_qps"),
        ):
            result = amap_provider._get("/test", {"city": "苏州"})

        self.assertIsNone(result)
        self.assertEqual(client.__enter__.return_value.get.call_count, 1)

    def test_qps_limit_is_independent_for_each_amap_service(self) -> None:
        with amap_provider._AMAP_RATE_LOCK:
            amap_provider._AMAP_NEXT_REQUEST_AT.clear()
        try:
            with (
                patch.object(amap_provider.time, "monotonic", return_value=100.0),
                patch.object(amap_provider.time, "sleep") as sleep,
            ):
                for _ in range(3):
                    amap_provider._throttle_amap_qps("/v5/place/text")
                for _ in range(3):
                    amap_provider._throttle_amap_qps("/v3/weather/weatherInfo")
            self.assertEqual(sleep.call_count, 4)
            self.assertAlmostEqual(
                amap_provider._AMAP_NEXT_REQUEST_AT["/v5/place/text"], 101.0
            )
            self.assertAlmostEqual(
                amap_provider._AMAP_NEXT_REQUEST_AT["/v3/weather/weatherInfo"], 101.0
            )
        finally:
            with amap_provider._AMAP_RATE_LOCK:
                amap_provider._AMAP_NEXT_REQUEST_AT.clear()

    def test_poi_20_keeps_rich_fields_and_allows_25_results(self) -> None:
        payload = {
            "status": "1",
            "pois": [
                {
                    "id": "B001",
                    "parent": "P001",
                    "name": "拙政园",
                    "address": "东北街178号",
                    "location": "120.629,31.324",
                    "type": "风景名胜",
                    "typecode": "110200",
                    "adcode": "320508",
                    "citycode": "0512",
                    "cityname": "苏州市",
                    "adname": "姑苏区",
                    "business": {
                        "opentime_today": "07:30-17:30",
                        "rating": "4.8",
                        "cost": "80",
                    },
                    "navi": {"entr_location": "120.630,31.323"},
                    "photos": [{"url": "https://example.test/poi.jpg"}],
                }
            ],
        }

        with patch.object(amap_provider, "_get", return_value=payload) as request:
            facts = amap_provider.poi_search_many(
                "拙政园", city="苏州市", limit=25, city_limit=True
            )

        path, params = request.call_args.args
        self.assertEqual(path, "/v5/place/text")
        self.assertEqual(params["page_size"], 25)
        self.assertEqual(params["city_limit"], "true")
        self.assertEqual(params["show_fields"], "business,navi,photos")
        self.assertEqual(facts[0].poi_id, "B001")
        self.assertEqual(facts[0].entrance_location, "120.630,31.323")
        self.assertEqual(facts[0].rating, 4.8)

    def test_poi_detail_batches_at_most_ten_ids(self) -> None:
        payload = {
            "status": "1",
            "pois": [{"id": "B001", "name": "拙政园"}],
        }
        ids = [f"B{i:03d}" for i in range(12)]

        with patch.object(amap_provider, "_get", return_value=payload) as request:
            amap_provider.poi_details(ids)

        path, params = request.call_args.args
        self.assertEqual(path, "/v5/place/detail")
        self.assertEqual(len(params["id"].split("|")), 10)

    def test_geocode_and_reverse_geocode_retain_administrative_codes(self) -> None:
        forward = {
            "status": "1",
            "geocodes": [
                {
                    "location": "120.585,31.299",
                    "adcode": "320508",
                    "city": "苏州市",
                    "citycode": "0512",
                    "district": "姑苏区",
                    "formatted_address": "江苏省苏州市姑苏区",
                }
            ],
        }
        reverse = {
            "status": "1",
            "regeocode": {
                "formatted_address": "江苏省苏州市姑苏区人民路",
                "addressComponent": {
                    "adcode": "320508",
                    "city": "苏州市",
                    "citycode": "0512",
                    "district": "姑苏区",
                },
            },
        }

        with patch.object(amap_provider, "_get", side_effect=[forward, reverse]):
            geocoded = amap_provider.geocode_detail("苏州市姑苏区人民路")
            reversed_detail = amap_provider.reverse_geocode_detail("120.585,31.299")

        self.assertEqual(geocoded.citycode, "0512")
        self.assertEqual(reversed_detail.adcode, "320508")

    def test_weather_city_resolution_prefers_district_query(self) -> None:
        payload = {
            "status": "1",
            "districts": [{"name": "苏州市", "adcode": "320500", "citycode": "0512"}],
        }
        with patch.object(amap_provider, "_get", return_value=payload) as request:
            adcode = amap_provider.resolve_city_adcode("苏州")

        path, params = request.call_args.args
        self.assertEqual(path, "/v3/config/district")
        self.assertEqual(params["subdistrict"], 0)
        self.assertEqual(adcode, "320500")

    def test_weather_marks_dates_outside_official_three_day_payload_unknown(self) -> None:
        start = date.today()
        casts = [
            {
                "date": (start + timedelta(days=offset)).isoformat(),
                "dayweather": "晴",
                "nightweather": "多云",
                "daytemp": "26",
                "nighttemp": "18",
                "daywind": "南",
                "nightwind": "南",
                "daypower": "3",
                "nightpower": "2",
            }
            for offset in range(3)
        ]
        payload = {
            "status": "1",
            "forecasts": [{"reporttime": "2026-08-04 10:00:00", "casts": casts}],
        }

        with patch.object(amap_provider, "_get", return_value=payload):
            facts = amap_provider.weather_range(
                "320500",
                start.isoformat(),
                (start + timedelta(days=4)).isoformat(),
                display_city="苏州",
            )

        self.assertEqual([fact.status for fact in facts], ["ok", "ok", "ok", "unknown", "unknown"])
        self.assertEqual(facts[0].city, "苏州")
        self.assertEqual(facts[0].day_temp_c, 26)
        self.assertEqual(facts[3].report_time, "2026-08-04 10:00:00")

    def test_route_20_uses_selected_mode_and_retains_alternatives(self) -> None:
        payload = {
            "status": "1",
            "route": {
                "taxi_cost": "28",
                "paths": [
                    {
                        "distance": "12500",
                        "restriction": "0",
                        "cost": {
                            "duration": "1800",
                            "tolls": "5",
                            "toll_distance": "2000",
                            "traffic_lights": "12",
                        },
                        "steps": [
                            {
                                "instruction": "沿人民路行驶",
                                "road_name": "人民路",
                                "step_distance": "1000",
                                "cost": {"duration": "180"},
                                "navi": {"action": "直行"},
                                "polyline": "120.1,31.1;120.2,31.2",
                            }
                        ],
                    }
                ],
            },
        }

        with patch.object(amap_provider, "_get", return_value=payload) as request:
            fact = amap_provider.route(
                "酒店",
                "景点",
                "120.1,31.1",
                "120.2,31.2",
                mode="driving",
                origin_poi_id="O1",
                destination_poi_id="D1",
                waypoint_locations=["120.15,31.15"],
                vehicle_plate="苏A12345",
                car_type=1,
                avoid_ferry=True,
            )

        path, params = request.call_args.args
        self.assertEqual(path, "/v5/direction/driving")
        self.assertEqual(params["origin_id"], "O1")
        self.assertEqual(params["waypoints"], "120.15,31.15")
        self.assertEqual(params["cartype"], 1)
        self.assertEqual(params["ferry"], 1)
        self.assertNotIn("tmcs", params["show_fields"])
        self.assertEqual(fact.duration_minutes, 30)
        self.assertEqual(fact.alternatives[0].traffic_lights, 12)
        self.assertEqual(fact.alternatives[0].steps[0].action, "直行")

    def test_transit_requires_citycodes_and_can_request_ten_options(self) -> None:
        payload = {
            "status": "1",
            "route": {
                "transits": [
                    {
                        "distance": "6000",
                        "duration": "2400",
                        "walking_distance": "800",
                        "cost": "4",
                        "segments": [],
                    }
                ]
            },
        }
        with patch.object(amap_provider, "_get", return_value=payload) as request:
            fact = amap_provider.route(
                "A",
                "B",
                "120.1,31.1",
                "120.2,31.2",
                mode="transit",
                origin_citycode="0512",
                destination_citycode="0512",
                alternatives=10,
                night_service=True,
            )

        _, params = request.call_args.args
        self.assertEqual(params["city1"], "0512")
        self.assertEqual(params["AlternativeRoute"], 10)
        self.assertEqual(params["nightflag"], 1)
        self.assertEqual(fact.status, "ok")

    def test_tool_contract_rejects_combined_poi_keywords(self) -> None:
        with self.assertRaises(ValidationError):
            tool_specs.PoiArgs.model_validate({"keyword": "景点|酒店", "city": "苏州"})
        parsed = tool_specs.PoiArgs.model_validate({"types": "110000|120000", "limit": 99})
        self.assertEqual(parsed.limit, 25)


class ParallelToolExecutionTest(TestCase):
    def test_independent_amap_calls_overlap_and_results_keep_keys(self) -> None:
        barrier = Barrier(3)
        lock = Lock()
        active = 0
        max_active = 0

        def execute(tool_name: str, arguments: dict) -> dict:
            nonlocal active, max_active
            with lock:
                active += 1
                max_active = max(max_active, active)
            barrier.wait(timeout=2)
            with lock:
                active -= 1
            return {"tool": tool_name, "status": "ok", "value": arguments["value"]}

        results = orchestrator._execute_external_batch(
            {
                "a": (tool_specs.TOOL_AMAP_POI_SEARCH, {"value": 1}),
                "b": (tool_specs.TOOL_AMAP_WEATHER_RANGE, {"value": 2}),
                "c": (tool_specs.TOOL_AMAP_ROUTE, {"value": 3}),
            },
            execute,
        )

        self.assertEqual(max_active, 3)
        self.assertEqual(list(results), ["a", "b", "c"])
        self.assertEqual(results["b"]["value"], 2)
