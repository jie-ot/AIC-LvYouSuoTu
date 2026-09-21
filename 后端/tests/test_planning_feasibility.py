from __future__ import annotations

from unittest import TestCase

from app.ai import planning_feasibility
from app.models.itinerary import ItineraryData

# The flight facts the model actually held in the 2026-08-05 北疆 run.
FLIGHT_FACT = {
    "fact_id": "fact_searchFlightItineraries_a1",
    "tool": "searchFlightItineraries",
    "status": "ok",
    "flight_no": "MF3433",
    "depart_datetime": "2026-08-09 13:40",
    "arrive_datetime": "2026-08-09 18:15",
    "depart_time": "13:40",
    "arrive_time": "18:15",
    "same_schedule_flight_nos": [],
}
ROUTE_FACT = {
    "fact_id": "fact_route_b2",
    "tool": "amap_route",
    "status": "ok",
    "origin": "乌鲁木齐丽海商旅酒店(植物园地铁站店)",
    "destination": "乌鲁木齐地窝堡国际机场",
    "mode": "transit",
    "distance_km": 14.72,
    "duration_minutes": 58,
}
FACTS = {FLIGHT_FACT["fact_id"]: FLIGHT_FACT, ROUTE_FACT["fact_id"]: ROUTE_FACT}


def _itinerary(
    schedules: list[dict],
    bookings: list[dict] | None = None,
    *,
    date: str = "2026-08-09",
    destination: str = "乌鲁木齐",
) -> ItineraryData:
    return ItineraryData.model_validate(
        {
            "trip_info": {
                "destination": destination,
                "start_date": date,
                "end_date": date,
                "date_label": "1天",
            },
            "preparations": [],
            "bookings": bookings or [],
            "food_recommendations": [],
            "itinerary": [
                {"id": "day_1", "date": date, "schedules": schedules}
            ],
        }
    )


def _padding(count: int = 2) -> list[dict]:
    return [
        {
            "id": f"pad_{index}",
            "time_period": "晚上",
            "activity": "酒店休整",
        }
        for index in range(count)
    ]


class FlightTimeConsistencyTest(TestCase):
    def test_departure_time_not_offered_by_the_cited_flight_is_rejected(self) -> None:
        data = _itinerary(
            [
                {
                    "id": "sch_fly",
                    "time_period": "上午",
                    "start_time": "09:00",
                    "end_time": "12:00",
                    "activity": "从南京出发，乘坐航班前往乌鲁木齐",
                    "transport": "航班",
                    "fact_refs": [FLIGHT_FACT["fact_id"]],
                },
                *_padding(),
            ]
        )

        problems = planning_feasibility.find_problems(data, FACTS)

        self.assertTrue(
            any("出发时间 09:00 不是所引用班次的真实" in item for item in problems),
            problems,
        )
        self.assertTrue(any("13:40" in item for item in problems), problems)

    def test_real_departure_and_arrival_times_pass(self) -> None:
        data = _itinerary(
            [
                {
                    "id": "sch_fly",
                    "time_period": "下午",
                    "start_time": "13:40",
                    "end_time": "18:15",
                    "activity": "乘 MF3433 航班从南京飞往乌鲁木齐",
                    "transport": "航班 MF3433",
                    "fact_refs": [FLIGHT_FACT["fact_id"]],
                },
                *_padding(),
            ]
        )

        self.assertEqual(planning_feasibility.find_problems(data, FACTS), [])

    def test_intercity_leg_without_any_transport_fact_is_rejected(self) -> None:
        data = _itinerary(
            [
                {
                    "id": "sch_fly",
                    "time_period": "上午",
                    "start_time": "09:00",
                    "activity": "乘飞机前往乌鲁木齐",
                    "transport": "航班",
                    "fact_refs": [],
                },
                *_padding(),
            ]
        )

        problems = planning_feasibility.find_problems(data, FACTS)

        self.assertTrue(
            any("没有引用任何航班/车次事实" in item for item in problems), problems
        )

    def test_invented_flight_number_is_rejected(self) -> None:
        data = _itinerary(
            [
                {
                    "id": "sch_fly",
                    "time_period": "下午",
                    "start_time": "13:40",
                    "end_time": "18:15",
                    "activity": "乘 CZ6666 航班前往乌鲁木齐",
                    "fact_refs": [FLIGHT_FACT["fact_id"]],
                },
                *_padding(),
            ]
        )

        problems = planning_feasibility.find_problems(data, FACTS)

        self.assertTrue(
            any("CZ6666" in item and "未经查询" in item for item in problems), problems
        )

    def test_a_code_written_without_spaces_is_still_seen(self) -> None:
        """Plans write 「乘CZ6666航班」; a \\b-based scan never fires there."""
        data = _itinerary(
            [
                {
                    "id": "sch_fly",
                    "time_period": "下午",
                    "start_time": "13:40",
                    "end_time": "18:15",
                    "activity": "南京禄口机场乘CZ6666航班飞往乌鲁木齐",
                    "fact_refs": [FLIGHT_FACT["fact_id"]],
                },
                *_padding(),
            ]
        )

        problems = planning_feasibility.find_problems(data, FACTS)

        self.assertTrue(
            any("CZ6666" in item and "未经查询" in item for item in problems), problems
        )

    def test_road_names_and_exits_are_not_mistaken_for_services(self) -> None:
        data = _itinerary(
            [
                {
                    "id": "sch_drive",
                    "time_period": "上午",
                    "activity": "沿 G30 高速行驶，从 A1 出口驶出，途经 X12 县道",
                    "place_name": "天山天池",
                },
                *_padding(),
            ]
        )

        self.assertEqual(planning_feasibility.find_problems(data, FACTS), [])


class TransportLegDetectionTest(TestCase):
    """Regressions from the 2026-08-07 flash plan, which read plausibly but
    boarded flights at times no flight departed."""

    def test_a_leg_named_only_by_its_flight_code_still_checks_the_clock(self) -> None:
        data = _itinerary(
            [
                {
                    "id": "sch_depart",
                    "time_period": "上午",
                    "start_time": "11:30",
                    "end_time": "12:40",
                    # No 「航班」/「飞机」 wording at all, just the code.
                    "activity": "南京禄口机场乘坐 MF3433 出发前往乌鲁木齐",
                    "fact_refs": [FLIGHT_FACT["fact_id"]],
                },
                *_padding(),
            ]
        )

        problems = planning_feasibility.find_problems(data, FACTS)

        self.assertTrue(
            any("出发时间 11:30" in item and "13:40" in item for item in problems),
            problems,
        )

    def test_a_row_leaning_only_on_the_flight_fact_is_treated_as_the_leg(self) -> None:
        data = _itinerary(
            [
                {
                    "id": "sch_arrive",
                    "time_period": "晚上",
                    "start_time": "20:30",
                    "end_time": "21:00",
                    "activity": "抵达乌鲁木齐地窝堡国际机场，行程结束",
                    "fact_refs": [FLIGHT_FACT["fact_id"]],
                },
                *_padding(),
            ]
        )

        problems = planning_feasibility.find_problems(data, FACTS)

        self.assertTrue(
            any("出发时间 20:30" in item for item in problems),
            problems,
        )

    def test_a_hotel_named_after_a_station_is_not_a_train_ride(self) -> None:
        """A 22-minute run was once discarded because the hotel was called
        「丹东火车站鸭绿江断桥亚朵酒店」."""
        data = _itinerary(
            [
                {
                    "id": "sch_lunch",
                    "time_period": "中午",
                    "start_time": "11:30",
                    "end_time": "13:00",
                    "activity": "返回酒店退房，在附近午餐",
                    "note": "可在安东老街或酒店附近用餐",
                    "place_name": "丹东火车站鸭绿江断桥亚朵酒店",
                    "fact_refs": [],
                },
                *_padding(),
            ]
        )

        self.assertEqual(planning_feasibility.find_problems(data, FACTS), [])

    def test_walking_to_the_station_is_not_the_train_itself(self) -> None:
        data = _itinerary(
            [
                {
                    "id": "sch_walk",
                    "time_period": "下午",
                    "start_time": "15:20",
                    "end_time": "15:40",
                    "activity": "步行前往高铁站候车",
                    "fact_refs": [],
                },
                *_padding(),
            ]
        )

        self.assertEqual(planning_feasibility.find_problems(data, FACTS), [])

    def test_a_transfer_to_the_airport_is_not_treated_as_the_leg(self) -> None:
        data = _itinerary(
            [
                {
                    "id": "sch_transfer",
                    "time_period": "上午",
                    "start_time": "11:30",
                    "end_time": "12:28",
                    "activity": "从酒店出发前往机场",
                    "place_name": "乌鲁木齐地窝堡国际机场",
                    "distance_km": 14.72,
                    "travel_minutes": 58,
                    "transport_mode": "transit",
                    "fact_refs": [ROUTE_FACT["fact_id"]],
                },
                *_padding(),
            ]
        )

        self.assertEqual(planning_feasibility.find_problems(data, FACTS), [])


class ClockSanityTest(TestCase):
    def test_zero_length_schedule_is_rejected(self) -> None:
        data = _itinerary(
            [
                {
                    "id": "sch",
                    "time_period": "上午",
                    "start_time": "11:30",
                    "end_time": "11:30",
                    "activity": "在国际大巴扎逛街",
                },
                *_padding(),
            ]
        )

        problems = planning_feasibility.find_problems(data, FACTS)

        self.assertTrue(any("时长为 0" in item for item in problems), problems)

    def test_overnight_leg_crossing_midnight_is_allowed(self) -> None:
        data = _itinerary(
            [
                {
                    "id": "sch",
                    "time_period": "晚上",
                    "start_time": "23:10",
                    "end_time": "07:20",
                    "activity": "夜宿酒店",
                },
                *_padding(),
            ]
        )

        self.assertEqual(planning_feasibility.find_problems(data, FACTS), [])


class BookingConsistencyTest(TestCase):
    # A real train the model did query, but then never boarded.
    RAIL_FACT = {
        "fact_id": "fact_rail_tickets_c3",
        "tool": "query_rail_tickets",
        "status": "ok",
        "train_no": "G1232",
        "depart_time": "09:34",
        "arrive_time": "19:28",
    }
    FACTS_WITH_RAIL = {**FACTS, RAIL_FACT["fact_id"]: RAIL_FACT}

    def test_booking_for_a_service_nobody_rides_is_rejected(self) -> None:
        data = _itinerary(
            [
                {
                    "id": "sch_fly",
                    "time_period": "下午",
                    "start_time": "13:40",
                    "end_time": "18:15",
                    "activity": "乘 MF3433 航班从南京飞往乌鲁木齐",
                    "fact_refs": [FLIGHT_FACT["fact_id"]],
                },
                *_padding(),
            ],
            bookings=[
                {
                    "type": "机票",
                    "details": "8月9日 MF3433 南京→乌鲁木齐 13:40-18:15",
                },
                {"type": "火车票", "details": "8月9日 G1232 南京南→丹东 09:34-19:28"},
            ],
        )

        problems = planning_feasibility.find_problems(data, self.FACTS_WITH_RAIL)

        self.assertTrue(
            any("G1232" in item and "没有任何日程乘坐它" in item for item in problems),
            problems,
        )

    def test_invented_booking_code_is_rejected(self) -> None:
        data = _itinerary(
            [
                {
                    "id": "sch_fly",
                    "time_period": "下午",
                    "start_time": "13:40",
                    "end_time": "18:15",
                    "activity": "乘 MF3433 航班从南京飞往乌鲁木齐",
                    "fact_refs": [FLIGHT_FACT["fact_id"]],
                },
                *_padding(),
            ],
            bookings=[{"type": "火车票", "details": "8月9日 G9999 南京南→丹东"}],
        )

        problems = planning_feasibility.find_problems(data, FACTS)

        self.assertTrue(
            any("G9999" in item and "不是任何已查询事实" in item for item in problems),
            problems,
        )

    def test_booking_matching_the_itinerary_passes(self) -> None:
        data = _itinerary(
            [
                {
                    "id": "sch_fly",
                    "time_period": "下午",
                    "start_time": "13:40",
                    "end_time": "18:15",
                    "activity": "乘 MF3433 航班从南京飞往乌鲁木齐",
                    "fact_refs": [FLIGHT_FACT["fact_id"]],
                },
                *_padding(),
            ],
            bookings=[
                {
                    "type": "机票",
                    "details": (
                        "8月9日 MF3433 南京禄口→乌鲁木齐地窝堡 13:40-18:15 "
                        "经济舱，请在航司或正规平台购买，电话 0415-2592799"
                    ),
                },
                {
                    "type": "酒店",
                    "details": "8月9日 全季酒店(乌鲁木齐红山店) 五纬路127号",
                },
            ],
        )

        self.assertEqual(planning_feasibility.find_problems(data, FACTS), [])


class RouteEvidenceTest(TestCase):
    def test_distance_without_any_route_fact_is_rejected(self) -> None:
        data = _itinerary(
            [
                {
                    "id": "sch_bazaar",
                    "time_period": "晚上",
                    "activity": "前往新疆国际大巴扎",
                    "place_name": "新疆国际大巴扎",
                    "distance_km": 8.0,
                    "travel_minutes": 20,
                    "transport_mode": "driving",
                    "fact_refs": [],
                },
                *_padding(),
            ]
        )

        problems = planning_feasibility.find_problems(data, FACTS)

        self.assertTrue(
            any("没有引用 amap_route 事实" in item for item in problems), problems
        )

    def test_distance_contradicting_the_cited_route_is_rejected(self) -> None:
        data = _itinerary(
            [
                {
                    "id": "sch_airport",
                    "time_period": "上午",
                    "activity": "前往机场",
                    "place_name": "乌鲁木齐地窝堡国际机场",
                    "distance_km": 74.0,
                    "transport_mode": "transit",
                    "fact_refs": [ROUTE_FACT["fact_id"]],
                },
                *_padding(),
            ]
        )

        problems = planning_feasibility.find_problems(data, FACTS)

        self.assertTrue(
            any("distance_km=74" in item and "14.72" in item for item in problems),
            problems,
        )

    def test_route_fact_reused_for_a_different_hotel_is_rejected(self) -> None:
        data = _itinerary(
            [
                {
                    "id": "sch_hotel",
                    "time_period": "晚上",
                    "activity": "入住全季酒店后休息",
                    "place_name": "全季酒店(乌鲁木齐红山店)",
                    "distance_km": 14.72,
                    "travel_minutes": 58,
                    "transport_mode": "transit",
                    "fact_refs": [ROUTE_FACT["fact_id"]],
                },
                *_padding(),
            ]
        )

        problems = planning_feasibility.find_problems(data, FACTS)

        self.assertTrue(
            any("不是所引路线事实的起终点" in item for item in problems), problems
        )

    def test_matching_route_endpoint_and_values_pass(self) -> None:
        data = _itinerary(
            [
                {
                    "id": "sch_airport",
                    "time_period": "上午",
                    "activity": "从酒店乘地铁前往机场",
                    "place_name": "乌鲁木齐地窝堡国际机场",
                    "distance_km": 14.72,
                    "travel_minutes": 58,
                    "transport_mode": "transit",
                    "fact_refs": [ROUTE_FACT["fact_id"]],
                },
                *_padding(),
            ]
        )

        self.assertEqual(planning_feasibility.find_problems(data, FACTS), [])

    def test_null_distance_needs_no_route_fact(self) -> None:
        data = _itinerary(
            [
                {
                    "id": "sch_walk",
                    "time_period": "下午",
                    "activity": "在禾木村漫步",
                    "place_name": "禾木风景区",
                    "transport_mode": "walking",
                    "fact_refs": [],
                },
                *_padding(),
            ]
        )

        self.assertEqual(planning_feasibility.find_problems(data, FACTS), [])


class DayShapeTest(TestCase):
    def test_thin_day_is_rejected(self) -> None:
        data = _itinerary(
            [
                {"id": "a", "time_period": "上午", "activity": "前往机场"},
                {"id": "b", "time_period": "中午", "activity": "休息"},
            ]
        )

        problems = planning_feasibility.find_problems(data, FACTS)

        self.assertTrue(any("只有 2 条日程" in item for item in problems), problems)

    def test_overstuffed_day_is_rejected(self) -> None:
        data = _itinerary(
            [
                {"id": f"s{index}", "time_period": "上午", "activity": "游玩"}
                for index in range(7)
            ]
        )

        problems = planning_feasibility.find_problems(data, FACTS)

        self.assertTrue(any("超过上限" in item for item in problems), problems)


class SeverityTest(TestCase):
    def test_day_shape_findings_do_not_block_shipping(self) -> None:
        data = _itinerary(
            [
                {"id": "a", "time_period": "上午", "activity": "前往机场"},
                {"id": "b", "time_period": "中午", "activity": "休息"},
            ]
        )

        details = planning_feasibility.find_problem_details(data, FACTS)

        self.assertTrue(details)
        self.assertFalse(any(problem.blocking for problem in details), details)

    def test_a_fabricated_flight_time_blocks_shipping(self) -> None:
        data = _itinerary(
            [
                {
                    "id": "sch_fly",
                    "time_period": "上午",
                    "start_time": "09:00",
                    "activity": "乘航班前往乌鲁木齐",
                    "fact_refs": [FLIGHT_FACT["fact_id"]],
                },
                *_padding(),
            ]
        )

        details = planning_feasibility.find_problem_details(data, FACTS)

        self.assertTrue(any(problem.blocking for problem in details), details)


class AutofixTest(TestCase):
    def test_unbacked_distance_is_cleared_and_annotated(self) -> None:
        data = _itinerary(
            [
                {
                    "id": "sch_bazaar",
                    "time_period": "晚上",
                    "activity": "前往新疆国际大巴扎",
                    "place_name": "新疆国际大巴扎",
                    "distance_km": 8.0,
                    "travel_minutes": 20,
                    "transport_mode": "driving",
                    "fact_refs": [],
                },
                *_padding(),
            ]
        )

        repaired, applied = planning_feasibility.autofix(data, FACTS)

        schedule = repaired.itinerary[0].schedules[0]
        self.assertIsNone(schedule.distance_km)
        self.assertIsNone(schedule.travel_minutes)
        self.assertIn("以地图实时导航为准", schedule.note or "")
        self.assertTrue(applied)
        self.assertEqual(
            planning_feasibility.find_problems(repaired, FACTS),
            [],
        )

    def test_contradicting_distance_snaps_to_the_cited_route(self) -> None:
        data = _itinerary(
            [
                {
                    "id": "sch_airport",
                    "time_period": "上午",
                    "activity": "从酒店乘地铁前往机场",
                    "place_name": "乌鲁木齐地窝堡国际机场",
                    "distance_km": 74.0,
                    "travel_minutes": 20,
                    "transport_mode": "transit",
                    "fact_refs": [ROUTE_FACT["fact_id"]],
                },
                *_padding(),
            ]
        )

        repaired, _ = planning_feasibility.autofix(data, FACTS)

        schedule = repaired.itinerary[0].schedules[0]
        self.assertEqual(schedule.distance_km, 14.72)
        self.assertEqual(schedule.travel_minutes, 58)
        self.assertEqual(planning_feasibility.find_problems(repaired, FACTS), [])

    def test_route_borrowed_from_another_place_loses_its_numbers(self) -> None:
        data = _itinerary(
            [
                {
                    "id": "sch_hotel",
                    "time_period": "晚上",
                    "activity": "入住全季酒店后休息",
                    "place_name": "全季酒店(乌鲁木齐红山店)",
                    "distance_km": 14.72,
                    "travel_minutes": 58,
                    "transport_mode": "transit",
                    "fact_refs": [ROUTE_FACT["fact_id"]],
                },
                *_padding(),
            ]
        )

        repaired, applied = planning_feasibility.autofix(data, FACTS)

        schedule = repaired.itinerary[0].schedules[0]
        self.assertIsNone(schedule.distance_km)
        self.assertTrue(any("起终点" in item for item in applied), applied)
        self.assertEqual(planning_feasibility.find_problems(repaired, FACTS), [])

    def test_stale_fact_reference_is_dropped(self) -> None:
        data = _itinerary(
            [
                {
                    "id": "sch",
                    "time_period": "上午",
                    "activity": "游览天山天池",
                    "fact_refs": ["fact_route_does_not_exist", ROUTE_FACT["fact_id"]],
                },
                *_padding(),
            ]
        )

        repaired, applied = planning_feasibility.autofix(data, FACTS)

        self.assertEqual(
            repaired.itinerary[0].schedules[0].fact_refs, [ROUTE_FACT["fact_id"]]
        )
        self.assertTrue(applied)

    def test_a_sound_itinerary_is_left_untouched(self) -> None:
        data = _itinerary(
            [
                {
                    "id": "sch_fly",
                    "time_period": "下午",
                    "start_time": "13:40",
                    "end_time": "18:15",
                    "activity": "乘 MF3433 航班从南京飞往乌鲁木齐",
                    "transport": "航班 MF3433",
                    "fact_refs": [FLIGHT_FACT["fact_id"]],
                },
                *_padding(),
            ]
        )

        repaired, applied = planning_feasibility.autofix(data, FACTS)

        self.assertEqual(applied, [])
        self.assertEqual(repaired, data)

    def test_a_named_flight_gets_its_real_departure_and_arrival(self) -> None:
        """The 2026-08-07 flash plan folded 1.5h of check-in into the leg itself."""
        data = _itinerary(
            [
                {
                    "id": "sch_fly",
                    "time_period": "上午",
                    "start_time": "11:00",
                    "end_time": "19:00",
                    "activity": "南京禄口机场乘 MF3433 航班飞往乌鲁木齐，值机需提前 2 小时",
                    "fact_refs": [FLIGHT_FACT["fact_id"]],
                },
                *_padding(),
            ]
        )

        repaired, applied = planning_feasibility.autofix(data, FACTS)

        schedule = repaired.itinerary[0].schedules[0]
        self.assertEqual(schedule.start_time, "13:40")
        self.assertEqual(schedule.end_time, "18:15")
        self.assertEqual(len(applied), 2, applied)
        self.assertEqual(planning_feasibility.find_problems(repaired, FACTS), [])

    def test_a_transfer_that_only_cites_the_flight_is_not_rewritten(self) -> None:
        data = _itinerary(
            [
                {
                    "id": "sch_to_airport",
                    "time_period": "上午",
                    "start_time": "11:00",
                    "end_time": "12:10",
                    # Names no code, so which minute it should start is a judgement.
                    "activity": "从酒店出发前往机场值机",
                    "fact_refs": [FLIGHT_FACT["fact_id"]],
                },
                *_padding(),
            ]
        )

        repaired, applied = planning_feasibility.autofix(data, FACTS)

        self.assertEqual(applied, [])
        self.assertEqual(repaired.itinerary[0].schedules[0].start_time, "11:00")

    def test_an_ambiguous_choice_between_two_flights_is_left_alone(self) -> None:
        second = {
            **FLIGHT_FACT,
            "fact_id": "fact_flight_2",
            "depart_datetime": "2026-08-09 18:20",
            "depart_time": "18:20",
        }
        facts = {**FACTS, second["fact_id"]: second}
        data = _itinerary(
            [
                {
                    "id": "sch_fly",
                    "time_period": "上午",
                    "start_time": "11:00",
                    "activity": "乘 MF3433 航班飞往乌鲁木齐",
                    "fact_refs": [FLIGHT_FACT["fact_id"], second["fact_id"]],
                },
                *_padding(),
            ]
        )

        repaired, applied = planning_feasibility.autofix(data, facts)

        self.assertEqual(applied, [])
        self.assertEqual(repaired.itinerary[0].schedules[0].start_time, "11:00")

    def test_a_fabricated_flight_time_is_left_to_the_model(self) -> None:
        data = _itinerary(
            [
                {
                    "id": "sch_fly",
                    "time_period": "上午",
                    "start_time": "09:00",
                    "activity": "乘航班前往乌鲁木齐",
                    "fact_refs": [FLIGHT_FACT["fact_id"]],
                },
                *_padding(),
            ]
        )

        repaired, applied = planning_feasibility.autofix(data, FACTS)

        self.assertEqual(applied, [])
        self.assertTrue(planning_feasibility.find_problems(repaired, FACTS))


class AnnotateUnresolvedTest(TestCase):
    """What ships when repair cannot settle a row: a caveat, not a lost plan."""

    def _plan_with_a_bad_departure(self) -> ItineraryData:
        return _itinerary(
            [
                {
                    "id": "sch_fly",
                    "time_period": "上午",
                    "start_time": "09:00",
                    "activity": "乘航班前往乌鲁木齐",
                    "note": "建议提前值机",
                    "fact_refs": [FLIGHT_FACT["fact_id"]],
                },
                *_padding(),
            ]
        )

    def test_the_offending_row_is_flagged_and_marked_unverified(self) -> None:
        data = self._plan_with_a_bad_departure()
        problems = planning_feasibility.find_problem_details(data, FACTS)

        annotated, applied = planning_feasibility.annotate_unresolved(data, problems)

        schedule = annotated.itinerary[0].schedules[0]
        self.assertEqual(schedule.fact_status, "unverified")
        self.assertIn(planning_feasibility.UNCONFIRMED_NOTE, schedule.note or "")
        self.assertIn("建议提前值机", schedule.note or "")
        self.assertTrue(applied)

    def test_untouched_rows_keep_their_original_state(self) -> None:
        data = self._plan_with_a_bad_departure()
        problems = planning_feasibility.find_problem_details(data, FACTS)

        annotated, _ = planning_feasibility.annotate_unresolved(data, problems)

        for schedule in annotated.itinerary[0].schedules[1:]:
            self.assertIsNone(schedule.fact_status)
            self.assertIsNone(schedule.note)

    def test_findings_with_no_row_become_plan_level_advisories(self) -> None:
        """Booking/day findings have no schedule_id — they must still surface."""
        data = _itinerary(
            [{"id": "a", "time_period": "上午", "activity": "游玩"}],
            bookings=[{"type": "火车票", "details": "8月9日 G9999 南京南→丹东"}],
        )
        problems = planning_feasibility.find_problem_details(data, FACTS)

        annotated, applied = planning_feasibility.annotate_unresolved(data, problems)

        self.assertTrue(any("G9999" in problem.message for problem in problems))
        self.assertTrue(any(problem.date and not problem.schedule_id for problem in problems))
        self.assertTrue(any(not problem.date and not problem.schedule_id for problem in problems))
        self.assertTrue(applied)
        self.assertTrue(
            any("2026-08-09" in item for item in annotated.advisories),
            annotated.advisories,
        )
        self.assertIn(planning_feasibility._PLAN_ADVISORY, annotated.advisories)

    def test_day_level_findings_do_not_depend_on_a_specific_city(self) -> None:
        """Any thin day must produce the same advisory shape, destination aside."""
        data = _itinerary(
            [
                {
                    "id": "only",
                    "time_period": "上午",
                    "activity": "在喀什老城散步",
                }
            ],
            date="2026-09-01",
            destination="喀什",
        )
        problems = [
            problem
            for problem in planning_feasibility.find_problem_details(data, {})
            if problem.date == "2026-09-01" and not problem.schedule_id
        ]
        self.assertTrue(problems)

        annotated, applied = planning_feasibility.annotate_unresolved(data, problems)

        expected = planning_feasibility._DAY_ADVISORY.format(date="2026-09-01")
        self.assertEqual(annotated.advisories, [expected])
        self.assertTrue(any("整单提醒" in item for item in applied))
        # Model-facing repair text must not leak into the traveller banner.
        self.assertFalse(any("请补足" in item for item in annotated.advisories))

    def test_model_authored_advisories_are_replaced_by_the_gate(self) -> None:
        data = self._plan_with_a_bad_departure()
        data.advisories = ["模型自己编的无关提醒"]
        problems = planning_feasibility.find_problem_details(data, FACTS)

        annotated, _ = planning_feasibility.annotate_unresolved(data, problems)

        self.assertNotIn("模型自己编的无关提醒", annotated.advisories)

    def test_annotating_twice_does_not_repeat_the_caveat(self) -> None:
        data = self._plan_with_a_bad_departure()
        problems = planning_feasibility.find_problem_details(data, FACTS)

        once, _ = planning_feasibility.annotate_unresolved(data, problems)
        twice, _ = planning_feasibility.annotate_unresolved(once, problems)

        note = twice.itinerary[0].schedules[0].note or ""
        self.assertEqual(note.count(planning_feasibility.UNCONFIRMED_NOTE), 1)


class FactRefIntegrityTest(TestCase):
    def test_unknown_fact_id_is_rejected(self) -> None:
        data = _itinerary(
            [
                {
                    "id": "sch",
                    "time_period": "上午",
                    "activity": "游览天山天池",
                    "fact_refs": ["fact_route_does_not_exist"],
                },
                *_padding(),
            ]
        )

        problems = planning_feasibility.find_problems(data, FACTS)

        self.assertTrue(
            any("引用了不存在的 fact_id" in item for item in problems), problems
        )
