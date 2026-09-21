from __future__ import annotations

from contextlib import nullcontext
from unittest import TestCase
from unittest.mock import Mock, patch

from app.ai import orchestrator, output_parser
from app.ai.clients.ark_chat_client import ChatTurn, ToolCall
from app.ai.schemas import PlanningIntakeResult
from app.ai.tools import tool_specs
from app.models.dto import PlanningBrief, PlanningChatMessage, PlanningRequest
from app.models.itinerary import ItineraryData
from app.services import planning_intake_service, planning_service


class PlanningIntakeTest(TestCase):
    def test_intake_can_execute_external_tool_and_then_return_brief(self) -> None:
        executor = Mock(return_value={"tool": "amap_poi_search", "status": "ok"})
        tool_turn = ChatTurn(
            tool_calls=[
                ToolCall(
                    id="call_1",
                    name="amap_poi_search",
                    arguments='{"keyword":"园林","city":"苏州"}',
                )
            ]
        )
        final_turn = ChatTurn(
            content=(
                '{"assistantMessage":"苏州园林选择很多，请再确认日期。",'
                '"brief":{"origin":"武汉","destinations":["苏州"]}}'
            )
        )

        with patch.object(
            orchestrator.ark_chat_client,
            "chat_messages",
            side_effect=[tool_turn, final_turn],
        ) as chat:
            result = orchestrator.collect_planning_requirements(
                messages=[PlanningChatMessage(role="user", content="苏州有哪些园林？")],
                previous_brief=None,
                memory_summary="",
                execute_tool=executor,
            )

        self.assertEqual(result.brief.destinations, ["苏州"])
        executor.assert_called_once_with(
            "amap_poi_search",
            {"keyword": "园林", "city": "苏州"},
        )
        self.assertEqual(chat.call_args_list[0].kwargs["tools"], tool_specs.PLANNING_INTAKE_TOOLS)
        self.assertEqual(
            chat.call_args_list[1].kwargs["tools"],
            tool_specs.PLANNING_INTAKE_TOOLS,
        )

    def test_model_intake_contract_accepts_prompt_camel_case(self) -> None:
        parsed = output_parser.parse_model_json(
            """
            {
              "assistantMessage": "请补充准确日期。",
              "brief": {
                "origin": "武汉",
                "destinations": ["苏州"],
                "startDate": null,
                "endDate": null,
                "travelerCount": 2,
                "interests": ["园林"]
              }
            }
            """,
            PlanningIntakeResult,
        )

        self.assertEqual(parsed.assistant_message, "请补充准确日期。")
        self.assertEqual(parsed.brief.traveler_count, 2)

    def test_deepseek_compact_intake_repairs_missing_brief_without_tools(
        self,
    ) -> None:
        invalid_final = ChatTurn(content='{"assistantMessage":"请核对行程。"}')
        repaired_final = ChatTurn(
            content=(
                '{"assistantMessage":"请核对行程。","brief":{'
                '"origin":"南京","destinations":["丹东","大连"],'
                '"startDate":"2026-08-07","endDate":"2026-08-11",'
                '"travelerCount":null,"budget":null,"transportPreference":null,'
                '"lodgingPreference":null,"interests":[],"constraints":[],'
                '"assumptions":[],"summary":"南京经丹东到大连"}}'
            )
        )
        executor = Mock()

        with (
            patch.object(
                orchestrator.ark_chat_client,
                "chat_messages",
                side_effect=[invalid_final, repaired_final],
            ) as chat,
        ):
            result = orchestrator.collect_planning_requirements(
                messages=[PlanningChatMessage(role="user", content="南京去丹东大连")],
                previous_brief=None,
                memory_summary="",
                execute_tool=executor,
                planning_model="deepseek-v4-pro",
            )

        self.assertEqual(result.brief.destinations, ["丹东", "大连"])
        executor.assert_not_called()
        first_call = chat.call_args_list[0].kwargs
        self.assertEqual(first_call["stage"], "planning_intake_compact")
        self.assertFalse(first_call["thinking_enabled"])
        repair_call = chat.call_args_list[1].kwargs
        self.assertEqual(repair_call["stage"], "planning_intake_compact_repair")
        self.assertFalse(repair_call["thinking_enabled"])
        self.assertEqual(repair_call["response_format"], {"type": "json_object"})

    def test_literal_null_dates_are_missing_and_cannot_reach_confirmation(self) -> None:
        brief = planning_intake_service.normalize_brief(
            PlanningBrief(
                origin="广州",
                destinations=["赛里木湖"],
                start_date="null",
                end_date="null",
                traveler_count=3,
            )
        )

        self.assertIsNone(brief.start_date)
        self.assertIsNone(brief.end_date)
        self.assertEqual(
            planning_intake_service.missing_required_fields(brief),
            ["startDate", "endDate"],
        )

    def test_complete_requirements_return_confirmation_before_generation(self) -> None:
        intake = PlanningIntakeResult(
            assistant_message="信息齐了，请先核对清单。",
            brief=PlanningBrief(
                origin="深圳",
                destinations=["乌鲁木齐", "赛里木湖"],
                start_date="2026-10-01",
                end_date="2026-10-07",
                interests=["自然风光"],
            ),
        )
        request = PlanningRequest(
            message="国庆去新疆",
            context=None,
            messages=[{"role": "user", "content": "国庆去新疆"}],
        )

        with (
            patch.object(
                planning_service.orchestrator,
                "collect_planning_requirements",
                return_value=intake,
            ),
            patch.object(
                planning_service.orchestrator,
                "plan_itinerary",
            ) as generate,
        ):
            response = planning_service._collect_requirements(
                user_id="test_user",
                request=request,
                memory_summary="偏好自然风光",
            )

        self.assertEqual(response.phase, "confirming")
        self.assertIsNone(response.itinerary)
        self.assertTrue(response.checklist)
        generate.assert_not_called()

    def test_checklist_omits_budget_and_long_distance_transport(self) -> None:
        checklist = planning_intake_service.build_checklist(
            PlanningBrief(
                origin="武汉",
                destinations=["苏州"],
                start_date="2026-08-01",
                end_date="2026-08-03",
                budget="5000 元",
                transport_preference="高铁",
            )
        )

        keys = {item.key for item in checklist}
        self.assertNotIn("budget", keys)
        self.assertNotIn("transport", keys)

    def test_confirmed_requirement_text_uses_only_deterministic_defaults(self) -> None:
        brief = PlanningBrief(
            origin="武汉",
            destinations=["苏州"],
            start_date="2026-08-01",
            end_date="2026-08-03",
        )

        text = planning_intake_service.confirmed_requirement_text(
            brief,
            "确认生成",
        )

        self.assertIn("2026-08-01 至 2026-08-03", text)
        self.assertIn("1 人（用户未说明，按默认值）", text)
        self.assertNotIn("None", text)

    def test_confirmation_gate_blocks_missing_dates_before_generation(self) -> None:
        request = PlanningRequest(
            message="确认生成",
            confirmed=True,
            brief=PlanningBrief(origin="武汉", destinations=["苏州"]),
        )

        with (
            patch.object(
                planning_service,
                "session_scope",
                return_value=nullcontext(object()),
            ),
            patch.object(
                planning_service.memory_service,
                "get_or_create_current_memory",
                return_value=object(),
            ),
            patch.object(
                planning_service.memory_service,
                "build_memory_summary",
                return_value="",
            ),
            patch.object(
                planning_service.orchestrator,
                "plan_itinerary",
            ) as generate,
        ):
            response = planning_service.plan("test_user", request)

        self.assertEqual(response.phase, "collecting")
        self.assertIsNone(response.itinerary)
        generate.assert_not_called()

    def test_complete_explicit_confirmation_reaches_existing_generator(self) -> None:
        request = PlanningRequest(
            message="确认生成",
            confirmed=True,
            brief=PlanningBrief(
                origin="武汉",
                destinations=["苏州"],
                start_date="2026-08-01",
                end_date="2026-08-03",
            ),
        )
        itinerary = ItineraryData.model_validate(
            {
                "trip_info": {
                    "destination": "苏州",
                    "start_date": "2026-08-01",
                    "end_date": "2026-08-03",
                    "date_label": "8月1日—8月3日",
                },
                "preparations": [],
                "bookings": [],
                "food_recommendations": [],
                "itinerary": [],
            }
        )

        with (
            patch.object(
                planning_service,
                "session_scope",
                return_value=nullcontext(object()),
            ),
            patch.object(
                planning_service.memory_service,
                "get_or_create_current_memory",
                return_value=object(),
            ),
            patch.object(
                planning_service.memory_service,
                "build_memory_summary",
                return_value="",
            ),
            patch.object(
                planning_service.travel_fact_service,
                "needs_facts",
                return_value=False,
            ),
            patch.object(
                planning_service.orchestrator,
                "plan_itinerary",
                return_value=itinerary,
            ) as generate,
            patch.object(
                planning_service.itinerary_validation_service,
                "normalize_schedule_order",
                return_value=[],
            ),
            patch.object(
                planning_service.itinerary_id_service,
                "align_ids",
                return_value=itinerary,
            ),
            patch.object(
                planning_service.itinerary_validation_service,
                "validate_itinerary",
            ),
        ):
            response = planning_service.plan("test_user", request)

        self.assertEqual(response.phase, "completed")
        self.assertIs(response.itinerary, itinerary)
        planning_message = generate.call_args.kwargs["message"]
        self.assertIn("用户已经确认以下旅行需求", planning_message)
        self.assertIn("2026-08-01 至 2026-08-03", planning_message)
