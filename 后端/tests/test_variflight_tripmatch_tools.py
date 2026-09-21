from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from pydantic import ValidationError

from app.ai import orchestrator
from app.ai.clients.ark_chat_client import ChatTurn, ToolCall
from app.ai.tools import (
    tool_specs,
    variflight_aviation_provider,
    variflight_tripmatch_provider,
)
from app.services import travel_fact_service
from app.models.dto import PlanningChatMessage


class VariflightToolSpecTests(unittest.TestCase):
    def test_exactly_three_variflight_tools_are_deepseek_only(self) -> None:
        names = {
            item["function"]["name"]
            for item in tool_specs.planning_external_tools_for_model(
                "deepseek-v4-pro"
            )
        }
        variflight_names = {name for name in names if name.startswith("searchFlight")}
        self.assertEqual(
            variflight_names,
            {
                "searchFlightItineraries",
                "searchFlightsTransferinfo",
                "searchFlightandTrainTransferinfo",
            },
        )
        unsupported_names = tool_specs.external_tool_names_for_model(
            "unsupported-model"
        )
        self.assertTrue(variflight_names.isdisjoint(unsupported_names))
        self.assertTrue(variflight_names.issubset(tool_specs.ARG_SCHEMAS))

    def test_unsupported_prompt_does_not_receive_variflight_tool_instructions(self) -> None:
        unsupported_prompt = orchestrator._load_planning_system_prompt(
            "unsupported-model"
        )
        deepseek_prompt = orchestrator._load_planning_system_prompt(
            "deepseek-v4-flash"
        )
        self.assertNotIn("searchFlightItineraries", unsupported_prompt)
        self.assertNotIn("searchFlightsTransferinfo", unsupported_prompt)
        self.assertIn("searchFlightItineraries", deepseek_prompt)
        self.assertIn("searchFlightsTransferinfo", deepseek_prompt)

    def test_unsupported_model_hallucinated_flight_tool_is_not_executed(self) -> None:
        executor = Mock()
        tool_turn = ChatTurn(
            tool_calls=[
                ToolCall(
                    id="flight_call",
                    name="searchFlightsTransferinfo",
                    arguments=(
                        '{"depcity":"WUH","arrcity":"SZX",'
                        '"depdate":"2026-08-20"}'
                    ),
                )
            ]
        )
        final_turn = ChatTurn(
            content=(
                '{"assistantMessage":"请继续确认需求。",'
                '"brief":{"origin":"武汉","destinations":["深圳"]}}'
            )
        )
        with patch.object(
            orchestrator.ark_chat_client,
            "chat_messages",
            side_effect=[tool_turn, final_turn],
        ) as chat:
            orchestrator.collect_planning_requirements(
                messages=[
                    PlanningChatMessage(role="user", content="8月20日武汉飞深圳")
                ],
                previous_brief=None,
                memory_summary="",
                execute_tool=executor,
                planning_model="unsupported-model",
            )
        executor.assert_not_called()
        first_tool_names = {
            tool["function"]["name"] for tool in chat.call_args_list[0].kwargs["tools"]
        }
        self.assertNotIn("searchFlightsTransferinfo", first_tool_names)

    def test_iata_codes_are_normalized_and_dates_are_validated(self) -> None:
        itinerary = tool_specs.FlightItinerariesArgs.model_validate(
            {
                "depCityCode": "wuh",
                "depDate": "2026-08-20",
                "arrCityCode": "szx",
            }
        )
        self.assertEqual(
            (itinerary.dep_city_code, itinerary.arr_city_code), ("WUH", "SZX")
        )
        transfer = tool_specs.FlightTrainTransferArgs.model_validate(
            {"depcity": "nkg", "arrcity": "szx", "depdate": "2026-09-08"}
        )
        self.assertEqual((transfer.depcity, transfer.arrcity), ("NKG", "SZX"))
        with self.assertRaises(ValidationError):
            tool_specs.FlightTrainTransferArgs.model_validate(
                {"depcity": "NKG", "arrcity": "SZX", "depdate": "2026-02-30"}
            )

    def test_deepseek_compact_intake_repairs_non_json_answer(self) -> None:
        natural_turn = ChatTurn(
            content="已查到 MU2477，07:55 起飞、09:40 到达。",
            reasoning_content="已根据工具结果回答",
        )
        repaired_turn = ChatTurn(
            content=(
                '{"assistantMessage":"已查到 MU2477，07:55 起飞、09:40 到达。",'
                '"brief":{"origin":"武汉","destinations":["深圳"],'
                '"startDate":"2026-08-20","endDate":null,"interests":null,'
                '"constraints":null,"assumptions":null,"summary":null}}'
            )
        )
        executor = Mock(return_value={"status": "ok", "candidates": []})
        with patch.object(
            orchestrator.ark_chat_client,
            "chat_messages",
            side_effect=[natural_turn, repaired_turn],
        ) as chat:
            result = orchestrator.collect_planning_requirements(
                messages=[
                    PlanningChatMessage(role="user", content="8月20日武汉飞深圳")
                ],
                previous_brief=None,
                memory_summary="",
                execute_tool=executor,
                planning_model="deepseek-v4-flash",
            )
        self.assertIn("MU2477", result.assistant_message)
        self.assertEqual(result.brief.interests, [])
        self.assertEqual(result.brief.summary, "")
        executor.assert_not_called()
        self.assertEqual(chat.call_count, 2)
        self.assertIsNone(chat.call_args_list[1].kwargs["tools"])
        self.assertFalse(chat.call_args_list[1].kwargs["thinking_enabled"])
        self.assertEqual(
            chat.call_args_list[1].kwargs["response_format"],
            {"type": "json_object"},
        )
        repair_messages = chat.call_args_list[1].kwargs["messages"]
        self.assertEqual(repair_messages[-2]["reasoning_content"], "已根据工具结果回答")


class VariflightProviderTests(unittest.TestCase):
    def test_missing_key_does_not_attempt_network(self) -> None:
        with (
            patch.object(variflight_tripmatch_provider.settings, "TOOLS_ENABLED", True),
            patch.object(
                variflight_tripmatch_provider.settings,
                "VARIFLIGHT_TRIPMATCH_MCP_ENABLED",
                True,
            ),
            patch.object(
                variflight_tripmatch_provider.settings,
                "VARIFLIGHT_API_KEY",
                "",
            ),
            patch.object(variflight_tripmatch_provider.asyncio, "run") as run,
            patch.object(variflight_tripmatch_provider, "log_event") as log_event,
        ):
            result = variflight_tripmatch_provider.search_flight_train_transfer_sync(
                "NKG", "SZX", "2026-09-08"
            )
        self.assertEqual(result.status, "provider_not_connected")
        self.assertEqual(result.error_code, "variflight_api_key_missing")
        self.assertEqual(result.diagnostic_stage, "configuration")
        self.assertIsNotNone(result.trace_id)
        run.assert_not_called()
        self.assertEqual(log_event.call_count, 2)
        self.assertEqual(log_event.call_args_list[0].kwargs["status"], "start")
        self.assertEqual(log_event.call_args_list[1].kwargs["status"], "failed")

    def test_failure_log_has_stage_http_diagnostics_and_redacts_key(self) -> None:
        secret = "super secret"
        failure = RuntimeError(
            "403 https://example.cn/mcp/?api_key=super+secret&session=1"
        )
        failure.response = SimpleNamespace(status_code=403)
        with (
            patch.object(
                variflight_tripmatch_provider,
                "_call_tool",
                new=AsyncMock(side_effect=failure),
            ),
            patch.object(variflight_tripmatch_provider, "log_event") as log_event,
        ):
            result = variflight_tripmatch_provider.call_streamable_tool_sync(
                "searchFlightItineraries",
                {"depCityCode": "WUH", "depDate": "2026-08-20", "arrCityCode": "SZX"},
                enabled=True,
                endpoint="https://example.cn/mcp/",
                api_key=secret,
                timeout_seconds=30,
                provider_label="Aviation",
            )
        self.assertEqual(result.error_code, "variflight_auth_failed")
        self.assertEqual(result.http_status, 403)
        self.assertEqual(result.exception_type, "RuntimeError")
        self.assertEqual(result.diagnostic_stage, "dispatch")
        finish = log_event.call_args_list[-1].kwargs
        self.assertEqual(finish["status"], "failed")
        self.assertEqual(finish["http_status"], 403)
        self.assertNotIn(secret, str(finish))
        self.assertNotIn("super+secret", str(finish))

    def test_authentication_url_replaces_existing_key(self) -> None:
        url = variflight_tripmatch_provider._authenticated_url(
            "https://example.cn/mcp/?x=1&api_key=old", "new secret"
        )
        self.assertEqual(url, "https://example.cn/mcp/?x=1&api_key=new+secret")
        self.assertNotIn("old", url)

    def test_error_diagnostics_redact_api_key(self) -> None:
        with patch.object(
            variflight_tripmatch_provider.settings,
            "VARIFLIGHT_API_KEY",
            "super secret",
        ):
            message = variflight_tripmatch_provider._safe_error_message(
                RuntimeError(
                    "401 https://example.cn/mcp/?api_key=super+secret&session=1"
                )
            )
        self.assertNotIn("super", message)
        self.assertIn("api_key=***", message)

    def test_mcp_result_preserves_structured_and_text_content(self) -> None:
        result = SimpleNamespace(
            structuredContent={"data": [{"flightNo": "CZ1234", "terminal": "T2"}]},
            content=[SimpleNamespace(text='{"meta":{"source":"tripmatch"}}')],
            isError=False,
        )
        outcome = variflight_tripmatch_provider._extract_result(result)
        self.assertTrue(outcome.ok)
        self.assertEqual(outcome.provider_payload["data"][0]["terminal"], "T2")
        self.assertEqual(outcome.content, [{"meta": {"source": "tripmatch"}}])
        self.assertIn("tripmatch", outcome.raw_text or "")

    def test_mcp_result_parses_prefixed_python_literal_content(self) -> None:
        result = SimpleNamespace(
            structuredContent=None,
            content=[
                SimpleNamespace(
                    text=(
                        "Flight itineraries: {'code': 200, 'message': 'Success', "
                        "'data': '查询到了23条符合要求的航班', "
                        "'request_id': 'upstream-1'}"
                    )
                )
            ],
            isError=False,
        )
        outcome = variflight_tripmatch_provider._extract_result(result)
        self.assertEqual(outcome.provider_payload["code"], 200)
        self.assertEqual(outcome.provider_payload["request_id"], "upstream-1")
        summary = travel_fact_service._tripmatch_output_summary(outcome)
        self.assertEqual(summary["reported_candidate_count"], 23)
        self.assertEqual(summary["upstream_request_id"], "upstream-1")


class VariflightExecutorTests(unittest.TestCase):
    @staticmethod
    def _provider_outcome(
        payload: dict,
    ) -> variflight_tripmatch_provider.TripmatchCallResult:
        return variflight_tripmatch_provider.TripmatchCallResult(
            status="ok",
            provider_payload=payload,
            raw_text="provider detail",
            content=[{"extra": "kept"}],
        )

    def test_itineraries_result_keeps_price_fields_and_logs_safe_summary(self) -> None:
        payload = {
            "data": [
                {
                    "flightNo": "ZH9999",
                    "depTime": "2026-08-20 08:10:00",
                    "arrTime": "2026-08-20 10:25:00",
                    "duration": "2小时15分",
                    "isTransfer": False,
                    "cabin": "经济舱",
                    "price": 650,
                }
            ]
        }
        with (
            patch.object(
                variflight_aviation_provider,
                "search_flight_itineraries_sync",
                return_value=self._provider_outcome(payload),
            ),
            patch.object(
                variflight_aviation_provider,
                "endpoint_identity",
                return_value="https://example.cn/mcp/",
            ),
            patch.object(
                variflight_aviation_provider, "is_configured", return_value=True
            ),
            patch.object(travel_fact_service, "_persist_log") as persist_log,
        ):
            result = travel_fact_service.execute_tool(
                user_id="u1",
                request_id="r1",
                task_type="planning",
                tool_name=tool_specs.TOOL_SEARCH_FLIGHT_ITINERARIES,
                arguments={
                    "depCityCode": "wuh",
                    "depDate": "2026-08-20",
                    "arrCityCode": "szx",
                },
            )
        self.assertEqual(result["status"], "ok")
        self.assertEqual(
            result["query"],
            {
                "depCityCode": "WUH",
                "depDate": "2026-08-20",
                "arrCityCode": "SZX",
            },
        )
        self.assertEqual(result["candidates"][0]["price"], 650)
        self.assertEqual(result["provider_parsed_content"], [{"extra": "kept"}])
        log_kwargs = persist_log.call_args.kwargs
        self.assertEqual(log_kwargs["tool_name"], "searchFlightItineraries")
        self.assertEqual(log_kwargs["input_summary"]["api_key_present"], True)
        self.assertNotIn("api_key", log_kwargs["input_summary"])

    def test_transfer_requires_separate_12306_verification(self) -> None:
        payload = {
            "transferPlans": [
                {
                    "segments": [
                        {"type": "flight", "flightNo": "CZ1234"},
                        {"type": "rail", "from": "广州南", "to": "深圳北"},
                    ]
                }
            ]
        }
        with (
            patch.object(
                variflight_tripmatch_provider,
                "search_flight_train_transfer_sync",
                return_value=self._provider_outcome(payload),
            ),
            patch.object(
                variflight_tripmatch_provider,
                "endpoint_identity",
                return_value="https://example.cn/mcp/",
            ),
            patch.object(
                variflight_tripmatch_provider, "is_configured", return_value=True
            ),
            patch.object(
                travel_fact_service.rail_mcp_provider,
                "query_rail_options_sync",
                side_effect=AssertionError("rail must be an explicit later tool call"),
            ),
            patch.object(travel_fact_service, "_persist_log"),
        ):
            result = travel_fact_service.execute_tool(
                user_id="u1",
                request_id="r1",
                task_type="planning",
                tool_name=tool_specs.TOOL_SEARCH_FLIGHT_TRAIN_TRANSFER,
                arguments={
                    "depcity": "NKG",
                    "arrcity": "SZX",
                    "depdate": "2026-09-08",
                },
            )
        self.assertEqual(result["status"], "ok")
        self.assertTrue(result["rail_verification"]["required"])
        self.assertEqual(result["rail_verification"]["tool"], "query_rail_tickets")

    def test_flight_transfer_keeps_segments_and_has_48_hour_horizon(self) -> None:
        payload = {
            "transferPlans": [
                {
                    "transferAirport": "CTU",
                    "averageDelay": 18,
                    "segments": [
                        {"flightNo": "3U8702", "terminal": "T1"},
                        {"flightNo": "3U8573", "timezone": "Asia/Shanghai"},
                    ],
                }
            ]
        }
        with (
            patch.object(
                variflight_aviation_provider,
                "search_flight_transfer_sync",
                return_value=self._provider_outcome(payload),
            ),
            patch.object(
                variflight_aviation_provider,
                "endpoint_identity",
                return_value="https://example.cn/mcp/",
            ),
            patch.object(
                variflight_aviation_provider, "is_configured", return_value=True
            ),
            patch.object(travel_fact_service, "_persist_log") as persist_log,
        ):
            result = travel_fact_service.execute_tool(
                user_id="u1",
                request_id="r1",
                task_type="planning",
                tool_name=tool_specs.TOOL_SEARCH_FLIGHT_TRANSFER,
                arguments={
                    "depcity": "SZX",
                    "arrcity": "URC",
                    "depdate": "2026-08-20",
                },
            )
        self.assertEqual(result["transfer_type"], "flight_to_flight")
        self.assertIn("48 小时", result["query_horizon"])
        self.assertEqual(result["candidates"][0]["averageDelay"], 18)
        self.assertEqual(
            persist_log.call_args.kwargs["tool_name"],
            "searchFlightsTransferinfo",
        )


if __name__ == "__main__":
    unittest.main()
