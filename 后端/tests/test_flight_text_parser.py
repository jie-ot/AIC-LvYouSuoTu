from __future__ import annotations

from unittest import TestCase

from app.ai.tools import flight_text_parser

# Verbatim shape of a real VariFlight Aviation MCP answer (2026-08 upstream).
REAL_ANSWER = (
    "根据您的需求，我为您查询到了29条符合要求的航班，最低价:1200元，最短耗时:4h35m。\n"
    "最低价航班为： 航班号：UQ2578，起飞时间：2026-08-09 17:55:00，"
    "到达时间：2026-08-10 01:05:00，耗时：7h10m，无需中转，超值经济舱价格：1200元\n"
    "最短耗时航班为： 航班号：MF3433，起飞时间：2026-08-09 13:40:00，"
    "到达时间：2026-08-09 18:15:00，耗时：4h35m，无需中转，经济舱价格：2150元\n"
    "除了上述方案外还为您推荐以下方案：\n"
    "1. 航班号：SC2185，起飞时间：2026-08-09 19:00:00，"
    "到达时间：2026-08-09 23:50:00，耗时：4h50m，无需中转，超值经济舱价格：1720元\n"
    "2. 航班号：CA4671，起飞时间：2026-08-09 19:00:00，"
    "到达时间：2026-08-09 23:50:00，耗时：4h50m，无需中转，经济舱价格：1720元\n"
    "\n请注意，以上信息仅供参考，具体的机票价格和可用性可能会随时变动。"
)


class FlightTextParserTest(TestCase):
    def test_parses_every_flight_from_the_prose_answer(self) -> None:
        candidates = flight_text_parser.parse_flight_text(REAL_ANSWER)

        self.assertEqual(
            [item["flight_no"] for item in candidates],
            ["UQ2578", "MF3433", "SC2185", "CA4671"],
        )
        shortest = candidates[1]
        self.assertEqual(shortest["depart_datetime"], "2026-08-09 13:40")
        self.assertEqual(shortest["arrive_datetime"], "2026-08-09 18:15")
        self.assertEqual(shortest["depart_time"], "13:40")
        self.assertEqual(shortest["arrive_time"], "18:15")
        self.assertEqual(shortest["duration_minutes"], 275)
        self.assertEqual(shortest["cabin"], "经济舱")
        self.assertEqual(shortest["price_cny"], 2150.0)
        self.assertEqual(shortest["selection_role"], "shortest_duration")
        self.assertTrue(shortest["is_direct"])
        self.assertFalse(shortest["arrives_next_day"])
        self.assertEqual(shortest["fact_status"], "reference")

    def test_flags_overnight_arrival_and_codeshare_siblings(self) -> None:
        candidates = flight_text_parser.parse_flight_text(REAL_ANSWER)
        by_no = {item["flight_no"]: item for item in candidates}

        self.assertTrue(by_no["UQ2578"]["arrives_next_day"])
        self.assertEqual(by_no["UQ2578"]["arrive_date"], "2026-08-10")
        self.assertEqual(by_no["SC2185"]["same_schedule_flight_nos"], ["CA4671"])
        self.assertTrue(by_no["CA4671"]["likely_codeshare"])
        self.assertFalse(by_no["MF3433"]["likely_codeshare"])

    def test_summary_keeps_upstream_aggregates(self) -> None:
        summary = flight_text_parser.parse_flight_summary(REAL_ANSWER)

        self.assertEqual(summary["upstream_reported_flight_count"], 29)
        self.assertEqual(summary["upstream_lowest_price_cny"], 1200.0)
        self.assertEqual(summary["upstream_shortest_duration_minutes"], 275)

    def test_departure_window_pins_the_real_departure_times(self) -> None:
        candidates = flight_text_parser.parse_flight_text(REAL_ANSWER)
        window = flight_text_parser.departure_window(candidates)

        self.assertEqual(window["earliest_departure"], "2026-08-09 13:40")
        self.assertEqual(window["latest_departure"], "2026-08-09 19:00")
        self.assertIn("不得自拟时间", window["constraint"])

    def test_provider_text_prefers_data_field_and_is_bounded(self) -> None:
        payload = {"code": 200, "data": "x" * 5000}

        text = flight_text_parser.provider_text(payload, "ignored")

        self.assertTrue(text.startswith("x" * 100))
        self.assertLess(len(text), 5000)
        self.assertIn("已截断", text)

    def test_no_flights_yields_no_candidates(self) -> None:
        self.assertEqual(flight_text_parser.parse_flight_text(None), [])
        self.assertEqual(flight_text_parser.parse_flight_text("暂无可用航班"), [])
