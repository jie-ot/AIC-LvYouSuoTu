"""Research rounds must not get slower as the history piles up.

Across six rounds of a real五日双城 run the per-round latency climbed 32s → 134s,
almost entirely because every earlier tool payload was still in the prompt. Facts
live in the registry and are re-supplied for the final synthesis, so the history
only needs to record what was already asked.
"""

from __future__ import annotations

import json
from unittest import TestCase

from app.ai import orchestrator


def _tool_message(tool: str, payload: dict) -> dict:
    return {
        "role": "tool",
        "tool_call_id": f"call_{tool}",
        "content": json.dumps(payload, ensure_ascii=False),
    }


ROUTE_RESULT = {
    "tool": "amap_route",
    "status": "ok",
    "fact_id": "fact_route_a1",
    "origin": "乌鲁木齐丽海商旅酒店",
    "destination": "乌鲁木齐地窝堡国际机场",
    "distance_km": 14.72,
    "duration_minutes": 58,
    "steps": ["沿迎宾路行驶 3 公里"] * 40,
}
FLIGHT_RESULT = {
    "tool": "searchFlightItineraries",
    "status": "ok",
    "candidates": [
        {
            "fact_id": f"fact_flight_{index}",
            "flight_no": f"MF34{index}0",
            "depart_datetime": "2026-08-09 13:40",
            "notes": "餐食、行李额、经停信息" * 20,
        }
        for index in range(6)
    ],
}


class ToolHistoryCompactionTest(TestCase):
    def test_old_payloads_shrink_to_a_digest_of_what_was_queried(self) -> None:
        messages = [
            {"role": "system", "content": "system"},
            _tool_message("route", ROUTE_RESULT),
            _tool_message("flight", FLIGHT_RESULT),
        ]
        original = [len(message["content"]) for message in messages]

        summary = orchestrator._compact_tool_history(messages, len(messages))

        self.assertIsNotNone(summary)
        self.assertEqual(summary["messages"], 2)
        self.assertGreater(summary["chars_saved"], 0)
        self.assertLess(len(messages[1]["content"]), original[1])
        self.assertLess(len(messages[2]["content"]), original[2])

    def test_the_digest_keeps_the_tool_status_and_every_fact_id(self) -> None:
        messages = [_tool_message("flight", FLIGHT_RESULT)]

        orchestrator._compact_tool_history(messages, 1)

        digest = json.loads(messages[0]["content"])
        self.assertEqual(digest["tool"], "searchFlightItineraries")
        self.assertEqual(digest["status"], "ok")
        self.assertEqual(digest["factCount"], 6)
        self.assertIn("fact_flight_0", digest["factIds"])
        # The payload itself must be gone, or nothing was saved.
        self.assertNotIn("行李额", messages[0]["content"])

    def test_messages_after_the_cutoff_are_untouched(self) -> None:
        messages = [
            _tool_message("route", ROUTE_RESULT),
            _tool_message("flight", FLIGHT_RESULT),
        ]
        recent = messages[1]["content"]

        orchestrator._compact_tool_history(messages, 1)

        self.assertEqual(messages[1]["content"], recent)

    def test_assistant_and_user_turns_are_never_rewritten(self) -> None:
        messages = [
            {"role": "user", "content": "去新疆玩一周"},
            {"role": "assistant", "content": "好的，我先查一下班次"},
        ]
        before = [message["content"] for message in messages]

        summary = orchestrator._compact_tool_history(messages, len(messages))

        self.assertIsNone(summary)
        self.assertEqual([message["content"] for message in messages], before)

    def test_compacting_twice_is_a_no_op(self) -> None:
        messages = [_tool_message("route", ROUTE_RESULT)]

        orchestrator._compact_tool_history(messages, 1)
        digested = messages[0]["content"]
        again = orchestrator._compact_tool_history(messages, 1)

        self.assertIsNone(again)
        self.assertEqual(messages[0]["content"], digested)

    def test_a_payload_that_is_not_json_is_left_alone(self) -> None:
        messages = [{"role": "tool", "tool_call_id": "x", "content": "not json"}]

        summary = orchestrator._compact_tool_history(messages, 1)

        self.assertIsNone(summary)
        self.assertEqual(messages[0]["content"], "not json")

    def test_an_already_tiny_result_is_not_made_bigger(self) -> None:
        messages = [_tool_message("finish", {"tool": "finish_research", "status": "ok"})]
        before = messages[0]["content"]

        orchestrator._compact_tool_history(messages, 1)

        self.assertEqual(messages[0]["content"], before)

    def test_facts_deselected_from_retention_are_discarded_not_digested(self) -> None:
        messages = [
            _tool_message("route", ROUTE_RESULT),
            _tool_message("flight", FLIGHT_RESULT),
        ]

        summary = orchestrator._compact_tool_history(
            messages,
            len(messages),
            retained_fact_ids={"fact_flight_0"},
        )

        self.assertIsNotNone(summary)
        self.assertGreaterEqual(summary["discarded"], 1)
        discarded = json.loads(messages[0]["content"])
        self.assertTrue(discarded[orchestrator._TOOL_HISTORY_DISCARDED_KEY])
        self.assertNotIn("丽海商旅", messages[0]["content"])
        kept = json.loads(messages[1]["content"])
        self.assertTrue(kept[orchestrator._TOOL_HISTORY_DIGEST_KEY])
        self.assertIn("fact_flight_0", kept["factIds"])

    def test_confirmation_checklist_user_turn_is_never_touched(self) -> None:
        checklist = (
            f"{orchestrator._CONFIRMATION_CHECKLIST_MARKER}"
            "用户已经确认以下旅行需求\n- 详细需求：晚上回南京"
        )
        messages = [
            {"role": "system", "content": "system"},
            {"role": "user", "content": checklist},
            _tool_message("route", ROUTE_RESULT),
        ]

        orchestrator._compact_tool_history(messages, len(messages))

        self.assertEqual(messages[1]["content"], checklist)

    def test_missing_checklist_message_is_restored_from_user_text(self) -> None:
        checklist = (
            f"{orchestrator._CONFIRMATION_CHECKLIST_MARKER}"
            "\n- 详细需求：傍晚去大连"
        )
        messages = [
            {"role": "system", "content": "system"},
            _tool_message("route", ROUTE_RESULT),
        ]

        orchestrator._ensure_confirmation_checklist_preserved(messages, checklist)

        self.assertEqual(messages[1]["role"], "user")
        self.assertIn("详细需求：傍晚去大连", messages[1]["content"])

