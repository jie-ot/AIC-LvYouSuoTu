"""A reasoning-only round must be retried, not accepted as an answer.

DeepSeek can burn the whole completion budget on reasoning tokens and return
``finish_reason=stop`` with an empty message. Observed in a real planning run
(deepseek-v4-flash: completion_tokens=8716, reasoning_tokens=8716, content=""),
which failed the whole request with "模型未返回合法 JSON".
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from app.ai.clients import ark_chat_client


def _response(content: str | None, *, reasoning: str = "x" * 100) -> SimpleNamespace:
    return SimpleNamespace(
        id="resp-1",
        choices=[
            SimpleNamespace(
                finish_reason="stop",
                message=SimpleNamespace(
                    content=content,
                    tool_calls=None,
                    reasoning_content=reasoning,
                ),
            )
        ],
        usage=None,
    )


class RecordingCompletions:
    def __init__(self, responses: list[SimpleNamespace]) -> None:
        self._responses = responses
        self.calls: list[dict] = []

    def create(self, **kwargs: object) -> SimpleNamespace:
        self.calls.append(kwargs)
        return self._responses[min(len(self.calls) - 1, len(self._responses) - 1)]


class EmptyFinalAnswerTest(TestCase):
    def _run(self, responses: list[SimpleNamespace], **overrides: object):
        completions = RecordingCompletions(responses)
        client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
        with (
            patch.object(ark_chat_client, "_get_client", return_value=client),
            patch.object(ark_chat_client, "_sleep_before_retry"),
        ):
            turn = ark_chat_client.chat_messages(
                messages=[{"role": "user", "content": "生成行程"}],
                tools=None,
                stage="planning_final",
                planning_model="deepseek-v4-pro",
                **overrides,
            )
        return turn, completions

    def test_reasoning_only_round_is_retried_without_thinking(self) -> None:
        turn, completions = self._run(
            [_response(""), _response('{"ok": true}')]
        )

        self.assertEqual(turn.content, '{"ok": true}')
        self.assertEqual(len(completions.calls), 2)
        first, second = completions.calls
        self.assertEqual(first["extra_body"]["thinking"], {"type": "enabled"})
        self.assertIn("reasoning_effort", first)
        # The retry must not repeat the failure mode that produced no answer.
        self.assertEqual(second["extra_body"]["thinking"], {"type": "disabled"})
        self.assertNotIn("reasoning_effort", second)

    def test_whitespace_only_content_counts_as_empty(self) -> None:
        turn, completions = self._run(
            [_response("   \n  "), _response('{"ok": true}')]
        )

        self.assertEqual(turn.content, '{"ok": true}')
        self.assertEqual(len(completions.calls), 2)

    def test_exhausting_attempts_hands_the_empty_turn_to_the_caller(self) -> None:
        """Each caller raises the error that fits its own stage, so don't preempt it."""
        turn, completions = self._run([_response("")])

        self.assertGreaterEqual(len(completions.calls), 2)
        self.assertEqual(turn.content, "")

    def test_empty_rounds_do_not_get_the_whole_transient_retry_budget(self) -> None:
        """Transient errors are cheap to retry; a burnt generation is not.

        The attempt count is generous so a network wobble cannot lose a run, but
        an empty answer costs a full 2–3 minute generation each time, so the two
        budgets must not be the same number.
        """
        _, completions = self._run([_response("")])

        self.assertLess(len(completions.calls), ark_chat_client._TRANSIENT_ATTEMPT_FLOOR)
        self.assertEqual(
            len(completions.calls), ark_chat_client._EMPTY_ANSWER_RETRIES + 1
        )

    def test_a_single_attempt_caller_does_not_retry(self) -> None:
        turn, completions = self._run([_response("")], max_attempts=1)

        self.assertEqual(len(completions.calls), 1)
        self.assertEqual(turn.content, "")

    def test_a_tool_call_round_with_no_content_is_a_valid_answer(self) -> None:
        """Research rounds legitimately return tool calls and no prose."""
        response = _response(None)
        response.choices[0].message.tool_calls = [
            SimpleNamespace(
                id="call-1",
                function=SimpleNamespace(name="amap_route", arguments="{}"),
            )
        ]
        completions = RecordingCompletions([response])
        client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
        with (
            patch.object(ark_chat_client, "_get_client", return_value=client),
            patch.object(ark_chat_client, "_sleep_before_retry"),
        ):
            turn = ark_chat_client.chat_messages(
                messages=[{"role": "user", "content": "研究"}],
                tools=[{"type": "function", "function": {"name": "amap_route"}}],
                stage="planning_research",
                planning_model="deepseek-v4-pro",
            )

        self.assertEqual(len(completions.calls), 1)
        self.assertEqual([call.name for call in turn.tool_calls], ["amap_route"])

    def test_an_empty_research_round_is_left_to_the_orchestrator(self) -> None:
        """With tools offered, an empty round is handled by the protocol loop."""
        completions = RecordingCompletions([_response("")])
        client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
        with (
            patch.object(ark_chat_client, "_get_client", return_value=client),
            patch.object(ark_chat_client, "_sleep_before_retry"),
        ):
            turn = ark_chat_client.chat_messages(
                messages=[{"role": "user", "content": "研究"}],
                tools=[{"type": "function", "function": {"name": "amap_route"}}],
                stage="planning_research",
                planning_model="deepseek-v4-pro",
            )

        self.assertEqual(len(completions.calls), 1)
        self.assertEqual(turn.content, "")
