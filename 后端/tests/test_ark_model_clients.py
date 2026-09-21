"""Small offline checks for the Ark migration; no provider calls or file writes."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

import httpx
from pydantic import ValidationError

from app.ai.clients import ark_chat_client as chat
from app.ai.clients import ark_image_client as images
from app.core.exceptions import AIGenerationError, ImageInputPolicyError
from app.models.dto import PlanningRequest


class ArkModelClientsTest(TestCase):
    def test_non_planning_and_default_planning_use_separate_providers(self) -> None:
        runtimes = []
        calls = []

        def create(**kwargs):
            calls.append(kwargs)
            return SimpleNamespace(
                choices=[SimpleNamespace(
                    message=SimpleNamespace(content='{"ok":true}', reasoning_content=None),
                    finish_reason="stop",
                )],
                usage=None, id="offline",
            )

        client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))

        def get_client(runtime):
            runtimes.append(runtime)
            return client

        with patch.object(chat, "_get_client", side_effect=get_client), patch.object(chat, "log_event"):
            for task in (chat.TASK_PHOTO_ANALYZE, chat.TASK_REPORT_DRAFT, chat.TASK_PLANNING, chat.TASK_PLANNING_INTAKE):
                chat.chat_json(task=task, system_prompt="JSON", user_text="offline")

        self.assertEqual([runtime.provider for runtime in runtimes], ["ark", "ark", "deepseek", "deepseek"])
        self.assertEqual(calls[0]["model"], "doubao-seed-2.1-turbo")
        self.assertEqual(calls[0]["reasoning_effort"], "medium")
        self.assertEqual(calls[0]["extra_body"], {"thinking": {"type": "enabled"}})
        self.assertNotIn("extra_query", calls[0])
        self.assertNotIn("tools", calls[0])
        self.assertIn("max_completion_tokens", calls[0])
        self.assertEqual(calls[2]["model"], "deepseek-v4-flash")
        self.assertIn("max_tokens", calls[2])

    def test_removed_planning_model_is_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            PlanningRequest(message="规划", planningModel="doubao-seed-2.0-pro")
        self.assertEqual(PlanningRequest(message="规划").planning_model, "deepseek-v4-flash")

    def test_encrypted_thinking_is_redacted(self) -> None:
        result = chat._loggable_payload({"reasoning_content": "summary-private", "encrypted_content": "cipher-private"})
        self.assertNotIn("summary-private", str(result))
        self.assertNotIn("cipher-private", str(result))

    def _image_request(self, status: int, payload: dict):
        requests = []

        def handle(request):
            requests.append(request)
            return httpx.Response(status, json=payload)

        client = httpx.Client(transport=httpx.MockTransport(handle))
        with (
            patch.object(images.settings, "ARK_IMAGE_API_KEY", "image-test-key"),
            patch.object(images.settings, "ARK_PLAN_API_KEY", "plan-test-key"),
            patch.object(images.httpx, "Client", return_value=client),
            patch.object(images, "log_event"),
        ):
            result = images.generate_image(prompt="postcard", image_data_urls=["data:image/jpeg;base64,AAAA"])
        return result, requests

    def test_image_request_uses_paid_endpoint_key_and_flat_openai_body(self) -> None:
        result, requests = self._image_request(200, {"data": [{"url": "https://example.com/output.jpg"}]})
        request = requests[0]
        body = json.loads(request.content)
        self.assertEqual(str(request.url), "https://ark.cn-beijing.volces.com/api/v3/images/generations")
        self.assertEqual(request.headers["Authorization"], "Bearer image-test-key")
        self.assertEqual(body["model"], "doubao-seedream-5-0-pro-260628")
        self.assertEqual(body["size"], "2K")
        self.assertEqual(body["response_format"], "url")
        self.assertNotIn("parameters", body)
        self.assertNotIn("sequential_image_generation", body)
        self.assertEqual(result.image_url, "https://example.com/output.jpg")

    def test_http_400_input_policy_error_keeps_existing_service_mapping(self) -> None:
        with self.assertRaises(ImageInputPolicyError):
            self._image_request(400, {"error": {"code": "InputImageSensitiveContentDetected.PrivacyInformation"}})

    def test_output_policy_error_is_not_an_input_policy_error(self) -> None:
        with self.assertRaises(AIGenerationError):
            self._image_request(400, {"error": {"code": "OutputImageSensitiveContentDetected"}})
