from __future__ import annotations

from unittest import TestCase

from app.core import planning_progress
from app.core.business_logging import call_in_current_context


class PlanningProgressTest(TestCase):
    def setUp(self) -> None:
        planning_progress.reset_for_tests()

    def tearDown(self) -> None:
        planning_progress.reset_for_tests()

    def test_without_a_token_reporting_is_a_no_op(self) -> None:
        with planning_progress.progress_session(None):
            planning_progress.report("researching", research_round=2)
        self.assertIsNone(planning_progress.snapshot(None))
        self.assertIsNone(planning_progress.snapshot("missing-token"))

    def test_stage_reports_move_percent_forward_and_expose_labels(self) -> None:
        with planning_progress.progress_session("tok-1", planning_model="deepseek-v3"):
            first = planning_progress.snapshot("tok-1")
            planning_progress.report("reading_memory")
            planning_progress.report(
                "researching",
                research_round=1,
                target_rounds=5,
                max_rounds=8,
            )
            researching = planning_progress.snapshot("tok-1")
            planning_progress.report("synthesizing", detail="依据 30 条事实编排行程")
            synthesizing = planning_progress.snapshot("tok-1")

        self.assertEqual(first["stage"], "queued")
        self.assertEqual(researching["phase"], "researching")
        self.assertEqual(researching["targetRounds"], 5)
        self.assertEqual(researching["stageLabel"], "正在查询真实交通、住宿与景点事实")
        self.assertGreater(researching["percent"], first["percent"])
        self.assertEqual(synthesizing["detail"], "依据 30 条事实编排行程")
        self.assertGreater(synthesizing["percent"], researching["percent"])
        self.assertEqual(synthesizing["planningModel"], "deepseek-v3")
        self.assertFalse(synthesizing["done"])

    def test_research_rounds_interpolate_and_never_go_backwards(self) -> None:
        with planning_progress.progress_session("tok-2"):
            percents = []
            for round_index in range(1, 6):
                planning_progress.report(
                    "researching",
                    research_round=round_index,
                    target_rounds=5,
                )
                percents.append(planning_progress.snapshot("tok-2")["percent"])
            # Extending research past the target must not rewind the bar.
            planning_progress.report(
                "researching",
                research_round=6,
                target_rounds=8,
            )
            extended = planning_progress.snapshot("tok-2")["percent"]

        self.assertEqual(percents, sorted(percents))
        self.assertGreaterEqual(extended, percents[-1])
        self.assertLessEqual(extended, planning_progress._STAGE_SPAN["researching"][1])

    def test_a_silent_stage_keeps_advancing_between_polls(self) -> None:
        """Synthesis is one model call of minutes with nothing to report; a bar
        frozen that long is indistinguishable from a hung request."""
        with planning_progress.progress_session("tok-slow"):
            planning_progress.report("synthesizing")
            first = planning_progress.snapshot("tok-slow")["percent"]
            session = planning_progress._sessions["tok-slow"]
            session.stage_started -= 90  # 90s into the call, still no report
            later = planning_progress.snapshot("tok-slow")["percent"]
            session.stage_started -= 10_000  # far past any plausible duration
            capped = planning_progress.snapshot("tok-slow")["percent"]

        start, end = planning_progress._STAGE_SPAN["synthesizing"]
        self.assertAlmostEqual(first, start, places=1)
        self.assertGreater(later, first)
        self.assertLess(later, end)
        # The band is a ceiling: an unusually slow stage must not claim the next
        # stage's progress, however long it runs.
        self.assertAlmostEqual(capped, end, places=1)

    def test_estimate_tracks_a_run_far_slower_than_the_default(self) -> None:
        with planning_progress.progress_session("tok-eta"):
            planning_progress.report("synthesizing")
            session = planning_progress._sessions["tok-eta"]
            session.started -= 400  # 400s in and only just synthesizing
            session.stage_started -= 40
            snapshot = planning_progress.snapshot("tok-eta")

        self.assertGreater(snapshot["estimatedRemainingMs"], 60_000)
        self.assertGreater(
            snapshot["estimatedTotalMs"], snapshot["elapsedMs"] + 60_000
        )

    def test_tool_activities_are_counted_and_capped(self) -> None:
        with planning_progress.progress_session("tok-3"):
            for index in range(planning_progress.MAX_RECENT_ACTIVITIES + 3):
                planning_progress.add_tool_activity(f"查询航班 {index}")
            snapshot = planning_progress.snapshot("tok-3")

        self.assertEqual(
            snapshot["toolCallCount"],
            planning_progress.MAX_RECENT_ACTIVITIES + 3,
        )
        self.assertEqual(
            len(snapshot["recentActivities"]),
            planning_progress.MAX_RECENT_ACTIVITIES,
        )
        self.assertEqual(snapshot["recentActivities"][-1], "查询航班 10")

    def test_worker_threads_report_into_the_same_session(self) -> None:
        with planning_progress.progress_session("tok-4"):
            call_in_current_context(
                planning_progress.add_tool_activity,
                "查询路线 南京→乌鲁木齐",
            )()
            snapshot = planning_progress.snapshot("tok-4")

        self.assertEqual(snapshot["toolCallCount"], 1)
        self.assertIn("查询路线 南京→乌鲁木齐", snapshot["recentActivities"])

    def test_finish_marks_done_and_freezes_the_estimate(self) -> None:
        with planning_progress.progress_session("tok-5"):
            planning_progress.finish()
            snapshot = planning_progress.snapshot("tok-5")

        self.assertEqual(snapshot["stage"], "completed")
        self.assertEqual(snapshot["percent"], 100.0)
        self.assertTrue(snapshot["done"])
        self.assertEqual(snapshot["estimatedRemainingMs"], 0)
        self.assertEqual(snapshot["estimatedTotalMs"], snapshot["elapsedMs"])

    def test_an_exception_records_the_failure_and_propagates(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "boom"):
            with planning_progress.progress_session("tok-6"):
                raise RuntimeError("boom")
        snapshot = planning_progress.snapshot("tok-6")

        self.assertEqual(snapshot["stage"], "failed")
        self.assertEqual(snapshot["phase"], "failed")
        self.assertEqual(snapshot["error"], "boom")
        self.assertTrue(snapshot["done"])

    def test_estimate_never_promises_a_finish_time_in_the_past(self) -> None:
        with planning_progress.progress_session("tok-7"):
            planning_progress.report("researching", research_round=1, target_rounds=5)
            session = planning_progress._sessions["tok-7"]
            # Simulate a run already slower than the projection.
            session.started -= 500
            snapshot = planning_progress.snapshot("tok-7")

        self.assertGreater(snapshot["estimatedTotalMs"], snapshot["elapsedMs"])
        self.assertGreater(snapshot["estimatedRemainingMs"], 0)

    def test_malformed_tokens_are_rejected_rather_than_rewritten(self) -> None:
        self.assertIsNone(planning_progress.normalize_token(None))
        self.assertIsNone(planning_progress.normalize_token("  "))
        self.assertIsNone(planning_progress.normalize_token("../../etc"))
        self.assertIsNone(planning_progress.normalize_token("plan 1"))
        self.assertIsNone(planning_progress.normalize_token("z" * 65))
        self.assertEqual(planning_progress.normalize_token(" plan-1_A "), "plan-1_A")
        self.assertEqual(planning_progress.normalize_token("z" * 64), "z" * 64)

    def test_old_sessions_are_evicted_when_the_registry_is_full(self) -> None:
        for index in range(planning_progress.MAX_TRACKED_SESSIONS + 5):
            with planning_progress.progress_session(f"tok-{index}"):
                pass
        self.assertLessEqual(
            len(planning_progress._sessions),
            planning_progress.MAX_TRACKED_SESSIONS,
        )
        self.assertIsNone(planning_progress.snapshot("tok-0"))
        self.assertIsNotNone(
            planning_progress.snapshot(
                f"tok-{planning_progress.MAX_TRACKED_SESSIONS + 4}"
            )
        )
