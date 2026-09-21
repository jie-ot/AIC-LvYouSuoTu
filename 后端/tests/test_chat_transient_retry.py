"""A network wobble must not throw away a ten-minute planning run.

Two real runs died at the intake call with three `APIConnectionError`s inside 28
seconds while the endpoint was reachable again moments later. The retry budget
was 3 attempts spaced 1s and 2s apart — shorter than the wobble itself.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from openai import APIConnectionError

from app.ai.clients import ark_chat_client
from app.core.exceptions import AIGenerationError


def _connection_error() -> APIConnectionError:
    return APIConnectionError(request=SimpleNamespace())  # type: ignore[arg-type]


def _answer() -> SimpleNamespace:
    return SimpleNamespace(
        id="resp-1",
        choices=[
            SimpleNamespace(
                finish_reason="stop",
                message=SimpleNamespace(
                    content='{"ok": true}',
                    tool_calls=None,
                    reasoning_content=None,
                ),
            )
        ],
        usage=None,
    )


class FlakyCompletions:
    """Fails the first `failures` calls, then answers."""

    def __init__(self, failures: int) -> None:
        self._failures = failures
        self.calls = 0

    def create(self, **_: object) -> SimpleNamespace:
        self.calls += 1
        if self.calls <= self._failures:
            raise _connection_error()
        return _answer()


class TransientRetryTest(TestCase):
    def _run(self, failures: int):
        completions = FlakyCompletions(failures)
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
            )
        return turn, completions

    def test_a_wobble_that_outlasts_three_tries_still_recovers(self) -> None:
        turn, completions = self._run(failures=4)

        self.assertEqual(turn.content, '{"ok": true}')
        self.assertEqual(completions.calls, 5)

    def test_a_dead_endpoint_still_fails_rather_than_hanging(self) -> None:
        completions = FlakyCompletions(failures=99)
        client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
        with (
            patch.object(ark_chat_client, "_get_client", return_value=client),
            patch.object(ark_chat_client, "_sleep_before_retry"),
            self.assertRaises(AIGenerationError),
        ):
            ark_chat_client.chat_messages(
                messages=[{"role": "user", "content": "生成行程"}],
                tools=None,
                stage="planning_final",
                planning_model="deepseek-v4-pro",
            )

        self.assertEqual(completions.calls, ark_chat_client._TRANSIENT_ATTEMPT_FLOOR)


class BackoffTest(TestCase):
    def _delays(self, attempts: int) -> list[float]:
        seen: list[float] = []
        with (
            patch.object(ark_chat_client.time, "sleep", seen.append),
            patch.object(ark_chat_client.random, "uniform", return_value=1.0),
        ):
            for attempt in range(attempts):
                ark_chat_client._sleep_before_retry(attempt, attempts)
        return seen

    def test_waits_double_instead_of_creeping_up_linearly(self) -> None:
        self.assertEqual(self._delays(5), [1.0, 2.0, 4.0, 8.0])

    def test_the_wait_is_capped_so_a_run_cannot_stall_indefinitely(self) -> None:
        delays = self._delays(9)

        self.assertTrue(all(delay <= ark_chat_client._MAX_RETRY_BACKOFF_SECONDS for delay in delays))
        self.assertEqual(delays[-1], ark_chat_client._MAX_RETRY_BACKOFF_SECONDS)

    def test_the_last_attempt_does_not_sleep_before_giving_up(self) -> None:
        self.assertEqual(len(self._delays(3)), 2)

    def test_concurrent_runs_do_not_retry_in_lockstep(self) -> None:
        """Identical delays would make parallel runs re-hammer a recovering endpoint."""
        seen: list[float] = []
        with patch.object(ark_chat_client.time, "sleep", seen.append):
            for _ in range(12):
                ark_chat_client._sleep_before_retry(2, 6)

        self.assertGreater(len(set(seen)), 1)
        for delay in seen:
            self.assertGreater(delay, 0)
            self.assertLessEqual(delay, ark_chat_client._MAX_RETRY_BACKOFF_SECONDS * 1.2)
