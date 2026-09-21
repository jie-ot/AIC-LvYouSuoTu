from __future__ import annotations

import json
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import mock_open, patch

from app.ai import orchestrator
from app.ai.clients import ark_chat_client
from app.core import business_logging
from app.core.exceptions import InvalidParamError
from app.models.dto import PlanningRequest
from app.models.itinerary import Schedule
from app.services import planning_service


class PlanningModelSelectionTest(TestCase):
    def test_deepseek_planning_gets_a_raised_transient_attempt_floor(self) -> None:
        """DeepSeek runs are long, so they buy extra patience for network wobbles."""
        deepseek = ark_chat_client._resolve_runtime("deepseek-v4-flash")
        doubao = ark_chat_client._resolve_runtime()

        self.assertEqual(
            ark_chat_client._chat_attempt_count(deepseek, None),
            ark_chat_client._TRANSIENT_ATTEMPT_FLOOR,
        )
        self.assertGreater(
            ark_chat_client._chat_attempt_count(deepseek, None),
            ark_chat_client._chat_attempt_count(doubao, None),
        )
        self.assertEqual(
            ark_chat_client._chat_attempt_count(deepseek, 1),
            1,
        )
        self.assertEqual(
            ark_chat_client._chat_attempt_count(doubao, None),
            max(1, ark_chat_client.settings.MODEL_MAX_RETRY + 1),
        )

    def test_long_distance_mode_is_kept_in_transport_text_not_amap_mode(self) -> None:
        schedule = Schedule.model_validate(
            {
                "id": "sch_1",
                "time_period": "上午",
                "activity": "乘 G1232 前往丹东",
                "transport": "G1232 高铁",
                "transport_mode": "rail/flight",
            }
        )

        self.assertIsNone(schedule.transport_mode)

    def test_deepseek_request_uses_official_thinking_parameters(self) -> None:
        runtime = ark_chat_client._resolve_runtime("deepseek-v4-pro")

        kwargs = ark_chat_client._completion_request_kwargs(
            runtime=runtime,
            messages=[{"role": "user", "content": "规划武汉到苏州"}],
            temperature=0.2,
            max_completion_tokens=16000,
            timeout=120,
            request_id="local-test",
        )

        self.assertEqual(kwargs["model"], "deepseek-v4-pro")
        self.assertEqual(kwargs["reasoning_effort"], "high")
        self.assertEqual(kwargs["extra_body"], {"thinking": {"type": "enabled"}})
        self.assertEqual(kwargs["max_tokens"], 16000)
        self.assertNotIn("max_completion_tokens", kwargs)
        self.assertNotIn("temperature", kwargs)
        self.assertNotIn("extra_query", kwargs)

    def test_deepseek_json_repair_disables_thinking(self) -> None:
        runtime = ark_chat_client._resolve_runtime("deepseek-v4-flash")
        kwargs = ark_chat_client._completion_request_kwargs(
            runtime=runtime,
            messages=[{"role": "user", "content": "只输出 JSON"}],
            temperature=0.0,
            max_completion_tokens=4000,
            timeout=120,
            request_id="json-repair-test",
            extra={"response_format": {"type": "json_object"}},
            thinking_enabled=False,
        )
        self.assertEqual(kwargs["extra_body"], {"thinking": {"type": "disabled"}})
        self.assertEqual(kwargs["response_format"], {"type": "json_object"})
        self.assertNotIn("reasoning_effort", kwargs)

    def test_deepseek_tool_turn_replays_reasoning_without_logging_content(self) -> None:
        turn = ark_chat_client.ChatTurn(
            content="",
            reasoning_content="provider-private-reasoning",
            tool_calls=[
                ark_chat_client.ToolCall(
                    id="scope",
                    name="declare_trip_scope",
                    arguments="{}",
                )
            ],
        )

        message = orchestrator._assistant_history_message(
            turn, "deepseek-v4-flash"
        )

        self.assertEqual(message["reasoning_content"], "provider-private-reasoning")
        self.assertEqual(message["tool_calls"][0]["function"]["name"], "declare_trip_scope")

    def test_conversation_rejects_switching_model(self) -> None:
        request = PlanningRequest.model_validate(
            {
                "message": "继续规划",
                "planningModel": "deepseek-v4-pro",
                "messages": [
                    {
                        "role": "user",
                        "content": "先去苏州",
                        "planningModel": "deepseek-v4-flash",
                    }
                ],
            }
        )

        with self.assertRaises(InvalidParamError):
            planning_service._validate_conversation_model(request)

    def test_old_client_defaults_to_deepseek_flash(self) -> None:
        request = PlanningRequest(message="去苏州")
        self.assertEqual(request.planning_model, "deepseek-v4-flash")

    def test_api_error_log_details_include_bounded_cause_chain(self) -> None:
        try:
            try:
                raise OSError("TLS handshake failed")
            except OSError as cause:
                raise RuntimeError("connection error") from cause
        except RuntimeError as exc:
            details = ark_chat_client._api_error_details(exc)

        self.assertEqual(details["error_type"], "RuntimeError")
        self.assertEqual(
            details["error_cause_chain"],
            [{"type": "OSError", "message": "TLS handshake failed"}],
        )

    def test_loggable_payload_keeps_text_and_redacts_image_data(self) -> None:
        payload = ark_chat_client._loggable_payload(
            {
                "messages": [
                    {"role": "system", "content": "完整系统提示"},
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "完整用户输入"},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": "data:image/png;base64,abcdef"
                                },
                            },
                        ],
                    },
                ],
                "api_key": "must-not-be-logged",
                "reasoning_content": "private-chain",
            }
        )

        self.assertEqual(
            payload["messages"][0]["content"],
            "完整系统提示",
        )
        self.assertEqual(payload["messages"][1]["content"][0]["text"], "完整用户输入")
        self.assertIn(
            "<redacted-data-url",
            payload["messages"][1]["content"][1]["image_url"]["url"],
        )
        self.assertEqual(payload["api_key"], "<redacted>")
        self.assertEqual(
            payload["reasoning_content"],
            "<redacted-private-reasoning chars=13>",
        )

    def test_chat_trace_logs_full_request_response_and_tool_arguments(self) -> None:
        completion = SimpleNamespace(
            id="response-1",
            choices=[
                SimpleNamespace(
                    finish_reason="tool_calls",
                    message=SimpleNamespace(
                        content="完整模型正文",
                        reasoning_content="private-reasoning",
                        tool_calls=[
                            SimpleNamespace(
                                id="call-1",
                                function=SimpleNamespace(
                                    name="amap_poi_search",
                                    arguments='{"keyword":"鸭绿江断桥"}',
                                ),
                            )
                        ],
                    ),
                )
            ],
            usage=SimpleNamespace(
                prompt_tokens=10,
                completion_tokens=20,
                total_tokens=30,
                completion_tokens_details=None,
            ),
        )
        client = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(create=lambda **_kwargs: completion)
            )
        )
        writer = mock_open()
        with (
            patch.object(ark_chat_client, "_get_client", return_value=client),
            patch.object(
                business_logging,
                "_build_log_path",
                return_value="unused-model-trace.log",
            ),
            patch("builtins.open", writer),
        ):
            with business_logging.business_task("trace_test"):
                ark_chat_client.chat_messages(
                    messages=[
                        {"role": "system", "content": "完整系统提示"},
                        {"role": "user", "content": "完整用户需求"},
                    ],
                    tools=[
                        {
                            "type": "function",
                            "function": {
                                "name": "amap_poi_search",
                                "description": "完整工具说明",
                                "parameters": {"type": "object"},
                            },
                        }
                    ],
                )

        rows = [json.loads(call.args[0]) for call in writer().write.call_args_list]
        request_row = next(row for row in rows if row["event"] == "model_chat_request")
        response_row = next(row for row in rows if row["event"] == "model_chat_response")
        self.assertEqual(request_row["messages"][1]["content"], "完整用户需求")
        self.assertEqual(
            request_row["tools"][0]["function"]["description"],
            "完整工具说明",
        )
        self.assertEqual(response_row["content"], "完整模型正文")
        self.assertEqual(
            response_row["tool_calls"][0]["arguments"],
            '{"keyword":"鸭绿江断桥"}',
        )
        self.assertNotIn("reasoning_content", response_row)
        self.assertTrue(response_row["reasoning_content_present"])
