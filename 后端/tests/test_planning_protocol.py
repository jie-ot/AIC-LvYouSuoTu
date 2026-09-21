from __future__ import annotations

import json
from unittest import TestCase
from unittest.mock import patch

from app.ai import orchestrator
from app.ai.clients.ark_chat_client import ChatTurn, ToolCall
from app.ai.prompts import load_prompt


class PlanningProtocolTest(TestCase):
    def test_planning_prompt_defines_transport_thresholds_and_flexible_mobility(
        self,
    ) -> None:
        prompt = load_prompt("planning_skill.md")

        self.assertIn("本次旅行请求中明确提出的硬要求和现实约束", prompt)
        self.assertIn("与本次要求不冲突的用户明确交通偏好", prompt)
        self.assertIn("才从时间合理性比较飞机、高铁和普通列车", prompt)
        self.assertIn("时间比较必须使用门到门总耗时", prompt)
        self.assertIn("最快高铁不超过 5 小时（含 5 小时）时通常优先高铁", prompt)
        self.assertIn("超过 5 小时但不足 7 小时时", prompt)
        self.assertIn("达到或超过 7 小时时通常优先飞机", prompt)
        self.assertIn("直达优先但不是硬规则", prompt)
        self.assertIn("可以选择铁路换乘或不同交通方式联程", prompt)
        self.assertIn("可组合公交地铁、步行、骑行、打车/自驾", prompt)
        self.assertIn("硬性偏好时必须服从", prompt)
        system_prompt = load_prompt("planning_system.md")
        self.assertIn("每天输出 4～6 个有意义的日程块", system_prompt)
        self.assertIn("最多 6 个", system_prompt)

    def test_scope_fact_state_finish_then_final_and_audit(self) -> None:
        itinerary = {
            "trip_info": {
                "destination": "苏州",
                "start_date": "2026-08-01",
                "end_date": "2026-08-01",
                "date_label": "8月1日",
            },
            "experience_summary": {
                "tripTheme": "园林慢游",
                "pace": "舒适",
                "intensity": 46,
                "highlights": ["拙政园"],
                "weatherSummary": "天气以临行前预报为准",
                "personalizationTags": ["人文优先"],
            },
            "preparations": [],
            "bookings": [],
            "food_recommendations": [],
            "itinerary": [],
        }
        turns = iter(
            [
                ChatTurn(
                    reasoning_content="scope reasoning",
                    tool_calls=[
                        ToolCall(
                            id="scope",
                            name="declare_trip_scope",
                            arguments=json.dumps(
                                {
                                    "origin": "武汉",
                                    "destinations": ["苏州"],
                                    "startDate": "2026-08-01",
                                    "endDate": "2026-08-01",
                                    "needsTransport": True,
                                    "needsHotel": False,
                                    "interests": ["园林"],
                                    "uncertainties": [],
                                },
                                ensure_ascii=False,
                            ),
                        ),
                        ToolCall(
                            id="poi",
                            name="amap_poi_search",
                            arguments='{"keyword":"拙政园","city":"苏州"}',
                        ),
                    ]
                ),
                ChatTurn(
                    reasoning_content="finish reasoning",
                    tool_calls=[
                        ToolCall(
                            id="finish",
                            name="finish_research",
                            arguments='{"completed":["主要景点"],"unresolved":[],"outline":["园林慢游"]}',
                        )
                    ]
                ),
                ChatTurn(content=json.dumps(itinerary, ensure_ascii=False)),
                ChatTurn(
                    content='{"passed":true,"missingQueries":[],"problems":[]}'
                ),
            ]
        )
        external_calls: list[str] = []
        model_calls: list[dict] = []
        business_events: list[tuple[str, dict]] = []

        def fake_chat_messages(**kwargs) -> ChatTurn:
            model_calls.append(kwargs)
            return next(turns)

        def fake_execute(tool_name: str, _arguments: dict) -> dict:
            external_calls.append(tool_name)
            return {
                "tool": tool_name,
                "status": "ok",
                "pois": [
                    {
                        "status": "ok",
                        "name": "拙政园",
                        "address": "苏州市姑苏区",
                        "location": "120.629,31.324",
                        "category": "风景名胜",
                    }
                ],
            }

        with (
            patch.object(orchestrator, "_critical_research_gaps", return_value=[]),
            patch.object(
                orchestrator.ark_chat_client,
                "chat_messages",
                side_effect=fake_chat_messages,
            ),
            patch.object(
                orchestrator,
                "log_event",
                side_effect=lambda event, **fields: business_events.append(
                    (event, fields)
                ),
            ),
        ):
            result = orchestrator._plan_with_tools(
                "system",
                "user",
                fake_execute,
                planning_model="deepseek-v4-pro",
            )

        self.assertEqual(result.trip_info.destination, "苏州")
        self.assertEqual(external_calls, ["amap_poi_search"])
        self.assertTrue(model_calls)
        self.assertTrue(
            all(call["planning_model"] == "deepseek-v4-pro" for call in model_calls)
        )
        # Final synthesis and audit must keep thinking on (never forced off) so
        # flight times and route evidence get reconciled, while still being
        # pinned to JSON output.
        for call in model_calls[2:4]:
            self.assertIsNone(call.get("thinking_enabled"))
            self.assertEqual(call["response_format"], {"type": "json_object"})
        second_round_messages = model_calls[1]["messages"]
        first_assistant = next(
            message
            for message in second_round_messages
            if message["role"] == "assistant"
        )
        self.assertEqual(first_assistant["reasoning_content"], "scope reasoning")
        round_results = [
            fields
            for event, fields in business_events
            if event == "planning_tool_round_result"
        ]
        self.assertEqual(round_results[0]["tool_names"], [
            "declare_trip_scope",
            "amap_poi_search",
        ])
        tool_results = [
            fields
            for event, fields in business_events
            if event == "planning_execute_tool"
            and fields.get("status") != "start"
        ]
        poi_result = next(
            item for item in tool_results if item["tool_name"] == "amap_poi_search"
        )
        self.assertEqual(poi_result["issued_fact_count"], 1)
        self.assertFalse(poi_result["cache_hit"])
        finish_result = next(
            item for item in tool_results if item["tool_name"] == "finish_research"
        )
        self.assertTrue(finish_result["research_finished"])

    def test_final_fact_selection_caps_candidates_and_compacts_raw_routes(self) -> None:
        facts = {
            f"poi-{index}": {
                "fact_id": f"poi-{index}",
                "tool": "amap_poi_search",
                "arguments": {"keyword": "景点", "city": "大连"},
                "name": f"景点{index}",
                "photo_url": "https://example.invalid/large.jpg",
            }
            for index in range(80)
        }
        facts["route"] = {
            "fact_id": "route",
            "tool": "amap_route",
            "arguments": {"origin": "甲", "destination": "乙"},
            "status": "ok",
            "alternatives": [
                {
                    "duration_minutes": 20,
                    "polyline": "1,2;3,4" * 1000,
                    "steps": [
                        {"instruction": "步行到车站", "polyline": "1,2;3,4"}
                    ],
                },
                {"duration_minutes": 30, "polyline": "5,6;7,8"},
            ],
        }
        facts["flight"] = {
            "fact_id": "flight",
            "tool": "searchFlightItineraries",
            "arguments": {"origin": "南京", "destination": "大连"},
            "status": "ok",
            "provider_raw_text": "raw" * 10000,
            "flight_no": "MU0001",
        }

        selected = orchestrator._select_planning_facts_for_final(facts)
        compact = orchestrator._compact_planning_facts(selected)
        encoded = json.dumps(compact, ensure_ascii=False)

        self.assertIn("flight", selected)
        self.assertIn("route", selected)
        self.assertEqual(
            sum(fact.get("tool") == "amap_poi_search" for fact in selected.values()),
            4,
        )
        self.assertNotIn("polyline", encoded)
        self.assertNotIn("provider_raw_text", encoded)
        self.assertNotIn("photo_url", encoded)
        route = next(fact for fact in compact if fact["fact_id"] == "route")
        self.assertEqual(len(route["alternatives"]), 1)

    def test_research_with_facts_forces_close_at_round_limit(self) -> None:
        itinerary = {
            "trip_info": {
                "destination": "苏州",
                "start_date": "2026-08-01",
                "end_date": "2026-08-01",
                "date_label": "8月1日",
            },
            "preparations": [],
            "bookings": [],
            "food_recommendations": [],
            "itinerary": [],
        }
        turns = iter(
            [
                ChatTurn(
                    tool_calls=[
                        ToolCall(
                            id="scope",
                            name="declare_trip_scope",
                            arguments=(
                                '{"origin":"武汉","destinations":["苏州"],'
                                '"startDate":"2026-08-01","endDate":"2026-08-01",'
                                '"needsTransport":true,"needsHotel":false,'
                                '"interests":[],"uncertainties":[]}'
                            ),
                        ),
                        ToolCall(
                            id="poi",
                            name="amap_poi_search",
                            arguments='{"keyword":"拙政园","city":"苏州"}',
                        ),
                    ]
                ),
                ChatTurn(
                    tool_calls=[
                        ToolCall(
                            id="state",
                            name="update_planning_fact_state",
                            arguments=(
                                '{"selectedFactIds":[],"remainingQueries":[]}'
                            ),
                        )
                    ]
                ),
                ChatTurn(content=json.dumps(itinerary, ensure_ascii=False)),
                ChatTurn(content='{"passed":true,"missingQueries":[],"problems":[]}'),
            ]
        )
        events: list[tuple[str, dict]] = []

        def fake_execute(tool_name: str, _arguments: dict) -> dict:
            return {
                "tool": tool_name,
                "status": "ok",
                "pois": [{"name": "拙政园", "status": "ok"}],
            }

        with (
            patch.object(orchestrator, "_TARGET_TOOL_ROUNDS", 2),
            patch.object(orchestrator, "_MAX_TOOL_ROUNDS", 2),
            patch.object(
                orchestrator.ark_chat_client,
                "chat_messages",
                side_effect=lambda **_kwargs: next(turns),
            ),
            patch.object(
                orchestrator,
                "log_event",
                side_effect=lambda event, **fields: events.append((event, fields)),
            ),
        ):
            result = orchestrator._plan_with_tools(
                "system",
                "user",
                fake_execute,
                planning_model="deepseek-v4-flash",
            )

        self.assertEqual(result.trip_info.destination, "苏州")
        forced = [fields for event, fields in events if event == "planning_research_forced_close"]
        self.assertEqual(len(forced), 1)
        self.assertEqual(
            forced[0]["reason"], "max_rounds_reached_with_critical_gaps"
        )

    def test_external_batch_retries_only_the_transient_query(self) -> None:
        calls = {"transient": 0, "stable": 0}

        def fake_execute(_tool_name: str, arguments: dict) -> dict:
            key = arguments["key"]
            calls[key] += 1
            if key == "transient" and calls[key] == 1:
                return {
                    "status": "timeout",
                    "error_code": "provider_timeout",
                    "retryable": True,
                }
            return {"status": "ok", "value": key}

        with (
            patch.object(orchestrator.settings, "TOOL_MAX_RETRY", 1),
            patch.object(orchestrator.time, "sleep"),
        ):
            results = orchestrator._execute_external_batch(
                {
                    "a": ("amap_poi_search", {"key": "transient"}),
                    "b": ("amap_poi_search", {"key": "stable"}),
                },
                fake_execute,
                max_total_attempts=3,
            )

        self.assertEqual(calls, {"transient": 2, "stable": 1})
        self.assertEqual(results["a"]["status"], "ok")
        self.assertEqual(results["a"]["_attempt_count"], 2)
        self.assertEqual(results["b"]["_attempt_count"], 1)

    def test_transient_failures_are_not_cacheable(self) -> None:
        self.assertFalse(
            orchestrator._cacheable_tool_result(
                {
                    "status": "timeout",
                    "error_code": "provider_timeout",
                    "retryable": True,
                }
            )
        )
        self.assertTrue(
            orchestrator._cacheable_tool_result(
                {
                    "status": "error",
                    "error_code": "invalid_args",
                    "retryable": False,
                }
            )
        )
        self.assertTrue(
            orchestrator._cacheable_tool_result(
                {"status": "unknown", "retryable": False}
            )
        )

    def test_research_extends_past_target_only_for_critical_gaps(self) -> None:
        itinerary = {
            "trip_info": {
                "destination": "苏州",
                "start_date": "2026-08-01",
                "end_date": "2026-08-01",
                "date_label": "8月1日",
            },
            "preparations": [],
            "bookings": [],
            "food_recommendations": [],
            "itinerary": [],
        }
        turns = iter(
            [
                ChatTurn(
                    tool_calls=[
                        ToolCall(
                            id="scope",
                            name="declare_trip_scope",
                            arguments=(
                                '{"origin":"武汉","destinations":["苏州"],'
                                '"startDate":"2026-08-01","endDate":"2026-08-01",'
                                '"needsTransport":true,"needsHotel":false,'
                                '"interests":[],"uncertainties":[]}'
                            ),
                        ),
                        ToolCall(
                            id="poi",
                            name="amap_poi_search",
                            arguments='{"keyword":"拙政园","city":"苏州"}',
                        ),
                    ]
                ),
                ChatTurn(
                    tool_calls=[
                        ToolCall(
                            id="state",
                            name="update_planning_fact_state",
                            arguments=(
                                '{"selectedFactIds":[],"remainingQueries":['
                                '"返程铁路交通"]}'
                            ),
                        )
                    ]
                ),
                ChatTurn(
                    tool_calls=[
                        ToolCall(
                            id="finish",
                            name="finish_research",
                            arguments=(
                                '{"completed":["已查景点"],'
                                '"unresolved":["返程待官方确认"],'
                                '"outline":["园林"]}'
                            ),
                        )
                    ]
                ),
                ChatTurn(content=json.dumps(itinerary, ensure_ascii=False)),
                ChatTurn(content='{"passed":true,"missingQueries":[],"problems":[]}'),
            ]
        )
        events: list[tuple[str, dict]] = []

        with (
            patch.object(orchestrator, "_TARGET_TOOL_ROUNDS", 2),
            patch.object(orchestrator, "_MAX_TOOL_ROUNDS", 3),
            patch.object(
                orchestrator.ark_chat_client,
                "chat_messages",
                side_effect=lambda **_kwargs: next(turns),
            ),
            patch.object(
                orchestrator,
                "log_event",
                side_effect=lambda event, **fields: events.append((event, fields)),
            ),
        ):
            result = orchestrator._plan_with_tools(
                "system",
                "user",
                lambda tool_name, _arguments: {
                    "tool": tool_name,
                    "status": "ok",
                    "pois": [{"name": "拙政园", "status": "ok"}],
                },
                planning_model="deepseek-v4-flash",
            )

        self.assertEqual(result.trip_info.destination, "苏州")
        extensions = [
            fields
            for event, fields in events
            if event == "planning_research_rounds_extended"
        ]
        self.assertEqual(len(extensions), 1)
        self.assertEqual(extensions[0]["extended_limit"], 3)

    def test_final_validation_uses_field_patch_before_full_regeneration(self) -> None:
        invalid = {
            "trip_info": {
                "destination": "苏州",
                "start_date": "2026-08-01",
                "end_date": "2026-08-01",
                "date_label": "8月1日",
            },
            "preparations": [],
            "bookings": [],
            "food_recommendations": [],
            "itinerary": [
                {
                    "id": "day-1",
                    "date": "2026-08-01",
                    "schedules": [
                        {
                            "id": "s-1",
                            "time_period": "09:00-11:00",
                            "activity": "参观拙政园",
                            "transport_mode": "spaceship",
                        }
                    ],
                }
            ],
        }
        calls: list[dict] = []

        def fake_chat_messages(**kwargs) -> ChatTurn:
            calls.append(kwargs)
            if len(calls) == 1:
                return ChatTurn(content=json.dumps(invalid, ensure_ascii=False))
            return ChatTurn(
                content=json.dumps(
                    {
                        "patches": [
                            {
                                "path": [
                                    "itinerary",
                                    0,
                                    "schedules",
                                    0,
                                    "transport_mode",
                                ],
                                "value": None,
                            }
                        ]
                    },
                    ensure_ascii=False,
                )
            )

        with patch.object(
            orchestrator.ark_chat_client,
            "chat_messages",
            side_effect=fake_chat_messages,
        ):
            result = orchestrator._generate_itinerary_from_research(
                system_prompt="system",
                user_text="user",
                scope={"destinations": ["苏州"]},
                retained_facts={},
                research_summary={"completed": []},
                stage="planning_final",
                planning_model="deepseek-v4-pro",
            )

        self.assertIsNone(result.itinerary[0].schedules[0].transport_mode)
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[1]["stage"], "planning_final_field_patch")
        self.assertEqual(calls[1]["max_completion_tokens"], 3000)

    def test_synthesis_goes_straight_to_the_deterministic_gate(self) -> None:
        """No advisory model round follows synthesis.

        The audit used to cost 3–7 minutes for a second opinion on coverage and
        pacing, and could regenerate the whole plan; truthfulness is enforced in
        code afterwards, so the round was removed.
        """
        itinerary = {
            "trip_info": {
                "destination": "苏州",
                "start_date": "2026-08-01",
                "end_date": "2026-08-01",
                "date_label": "8月1日",
            },
            "preparations": [],
            "bookings": [],
            "food_recommendations": [],
            "itinerary": [],
        }
        turns = iter(
            [
                ChatTurn(
                    tool_calls=[
                        ToolCall(
                            id="scope",
                            name="declare_trip_scope",
                            arguments=(
                                '{"origin":"武汉","destinations":["苏州"],'
                                '"startDate":"2026-08-01","endDate":"2026-08-01",'
                                '"needsTransport":true,"needsHotel":false,'
                                '"interests":[],"uncertainties":[]}'
                            ),
                        ),
                        ToolCall(
                            id="poi",
                            name="amap_poi_search",
                            arguments='{"keyword":"拙政园","city":"苏州"}',
                        ),
                    ]
                ),
                ChatTurn(
                    tool_calls=[
                        ToolCall(
                            id="finish",
                            name="finish_research",
                            arguments=(
                                '{"completed":["景点"],"unresolved":[],'
                                '"outline":["园林"]}'
                            ),
                        )
                    ]
                ),
                ChatTurn(content=json.dumps(itinerary, ensure_ascii=False)),
            ]
        )
        external_calls: list[str] = []
        events: list[str] = []
        stages: list[str] = []

        def fake_execute(tool_name: str, _arguments: dict) -> dict:
            external_calls.append(tool_name)
            return {
                "tool": tool_name,
                "status": "ok",
                "pois": [{"name": "拙政园", "status": "ok"}],
            }

        with (
            patch.object(orchestrator, "_critical_research_gaps", return_value=[]),
            patch.object(
                orchestrator.ark_chat_client,
                "chat_messages",
                side_effect=lambda **kwargs: (
                    stages.append(kwargs.get("stage")),
                    next(turns),
                )[1],
            ),
            patch.object(
                orchestrator,
                "log_event",
                side_effect=lambda event, **_fields: events.append(event),
            ),
        ):
            result = orchestrator._plan_with_tools(
                "system",
                "user",
                fake_execute,
                planning_model="deepseek-v4-flash",
            )

        self.assertEqual(result.trip_info.destination, "苏州")
        self.assertEqual(external_calls, ["amap_poi_search"])
        self.assertNotIn("planning_audit", stages)
        self.assertEqual(stages, ["planning_research", "planning_research", "planning_final"])
