"""Quota acceptance checks with isolated databases and no paid model calls.

Run from 后端: python -B -m unittest discover -s tests -p test_usage_limits.py -v
"""

from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Barrier
import unittest
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlmodel import SQLModel

from app.core.config import settings
from app.core.exceptions import AIGenerationError, UsageLimitError
from app.db import accounts, session as travel_db
from app.main import create_app
from app.models import tables  # noqa: F401 -- register the complete travel schema
from app.models.account import AccountBase
from app.models.dto import GenerateResult, PlanningResponse
from app.models.itinerary import ItineraryData
from app.services import account_service, generation_service, planning_service, usage_service


class UsageLimitsTest(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory(prefix="lvyousuotu-usage-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.auth_url = f"sqlite:///{(self.root / 'auth.db').as_posix()}"
        identity_engine = create_engine(self.auth_url, connect_args={"check_same_thread": False})
        business_engine = create_engine(
            f"sqlite:///{(self.root / 'travel.db').as_posix()}",
            connect_args={"check_same_thread": False},
        )
        self.addCleanup(identity_engine.dispose)
        self.addCleanup(business_engine.dispose)
        AccountBase.metadata.create_all(identity_engine)
        SQLModel.metadata.create_all(business_engine)
        patches = [
            patch.object(accounts, "engine", identity_engine),
            patch.object(travel_db, "engine", business_engine),
            patch.object(settings, "AUTH_DEMO_PASSWORD", "quota-test-password"),
            patch.object(settings, "AUTH_DEMO_LOGIN_ENABLED", True),
            patch.object(settings, "STATIC_ROOT", str(self.root / "static")),
            patch("app.core.business_logging._build_log_path", side_effect=lambda *_: str(
                self.root / f"{uuid4().hex}.log",
            )),
        ]
        for item in patches:
            self.enterContext(item)
        account_service.ensure_accounts()
        self.login = account_service.register("quota_user", "quota-test-password")
        self.user_id = self.login["user"]["id"]
        self.headers = {"Authorization": f"Bearer {self.login['token']}"}
        self.client = TestClient(create_app())
        self.addCleanup(self.client.close)
        self.itinerary = ItineraryData(
            trip_info={
                "destination": "杭州", "start_date": "2026-11-01",
                "end_date": "2026-11-01", "date_label": "11 月 1 日",
            },
            preparations=[], bookings=[], food_recommendations=[], itinerary=[],
        )
        self.planner = self.enterContext(patch.object(planning_service, "plan", return_value=PlanningResponse(
            phase="completed", assistant_message="已完成", planning_model="deepseek-v4-flash",
            itinerary=self.itinerary,
        )))
        self.generator = self.enterContext(patch.object(
            generation_service, "_generate_new", side_effect=self._complete_generation,
        ))

    def _complete_generation(self, user_id, request, operation_id):
        result = GenerateResult(
            postcard_group=None, report=None, operation_id=operation_id,
            postcard_status="success" if request.options.generate_postcards else "skipped",
            report_status="success" if request.options.generate_report else "skipped",
        )
        generation_service._finalize_operation(operation_id, result)
        return result

    def plan(self, *, refine=False, headers=None):
        payload = {"message": "调整为轻松一点的行程" if refine else "去杭州旅行", "confirmed": True}
        if refine:
            payload["context"] = self.itinerary.model_dump()
        return self.client.post("/api/ai/planning", json=payload, headers=headers or self.headers).json()

    def generate(self, *, postcards=True, report=False, request_id=None, headers=None):
        return self.client.post("/api/generate", json={
            "photos": [
                {"assetId": f"photo_{index}", "imageUrl": f"/static/uploads/{index}.jpg",
                 "takenAt": None, "location": None}
                for index in range(10 if report else 1)
            ],
            "requirements": "", "clientRequestId": request_id or uuid4().hex,
            "options": {"generatePostcards": postcards, "generateReport": report, "postcardCount": 5},
        }, headers=headers or self.headers).json()

    def assert_limit(self, response):
        self.assertEqual(response["code"], 1008, response)
        self.assertEqual(response["message"], "超出使用上限")

    def test_new_plans_and_ai_refinements_share_three_credits(self):
        self.assertEqual(self.plan()["code"], 0)
        self.assertEqual(self.plan(refine=True)["code"], 0)
        self.assertEqual(self.plan(refine=True)["code"], 0)
        self.assert_limit(self.plan(refine=True))
        self.assert_limit(self.plan())
        self.assertEqual(self.planner.call_count, 3)

    def test_postcards_reports_and_combined_generation_share_three_credits(self):
        self.assertEqual(self.generate()["code"], 0)
        self.assertEqual(self.generate(postcards=False, report=True)["code"], 0)
        self.assertEqual(self.generate(postcards=True, report=True)["code"], 0)
        self.assert_limit(self.generate())
        self.assert_limit(self.generate(postcards=False, report=True))
        self.assert_limit(self.generate(postcards=True, report=True))
        self.assertEqual(self.generator.call_count, 3)

    def test_feature_allowances_are_independent(self):
        for _ in range(3):
            self.assertEqual(self.generate()["code"], 0)
        for _ in range(3):
            self.assertEqual(self.plan()["code"], 0)
        self.assert_limit(self.generate())
        self.assert_limit(self.plan())

    def test_requirement_chat_and_confirmation_do_not_consume_credits(self):
        for phase in ("collecting", "confirming"):
            self.planner.return_value = PlanningResponse(
                phase=phase, assistant_message="请补充或确认需求", planning_model="deepseek-v4-flash",
            )
            for _ in range(4):
                self.assertEqual(self.plan()["code"], 0)
        self.planner.return_value = PlanningResponse(
            phase="completed", assistant_message="已完成", planning_model="deepseek-v4-flash",
            itinerary=self.itinerary,
        )
        for _ in range(3):
            self.assertEqual(self.plan()["code"], 0)
        self.assert_limit(self.plan())

    def test_failed_planning_returns_the_credit(self):
        self.planner.side_effect = AIGenerationError("离线模拟失败")
        for _ in range(4):
            self.assertEqual(self.plan()["code"], 1001)
        self.planner.side_effect = None
        for _ in range(3):
            self.assertEqual(self.plan()["code"], 0)
        self.assert_limit(self.plan())

    def test_failed_generation_can_retry_without_losing_a_credit(self):
        request_id = uuid4().hex
        self.generator.side_effect = AIGenerationError("离线模拟失败")
        self.assertEqual(self.generate(request_id=request_id)["code"], 1001)
        self.generator.side_effect = self._complete_generation
        self.assertEqual(self.generate(request_id=request_id)["code"], 0)
        for _ in range(2):
            self.assertEqual(self.generate()["code"], 0)
        self.assert_limit(self.generate())

    def test_completed_generation_replay_remains_available_after_exhaustion(self):
        request_id = uuid4().hex
        first = self.generate(request_id=request_id)
        self.assertEqual(first["code"], 0)
        for _ in range(2):
            self.assertEqual(self.generate()["code"], 0)
        for _ in range(2):
            self.assertEqual(self.generate(request_id=request_id), first)
        self.assertEqual(self.generator.call_count, 3)
        self.assert_limit(self.generate())

    def test_accounts_have_independent_allowances(self):
        for _ in range(3):
            self.assertEqual(self.plan()["code"], 0)
        other = account_service.register("another_user", "quota-test-password")
        other_headers = {"Authorization": f"Bearer {other['token']}"}
        self.assertEqual(self.plan(headers=other_headers)["code"], 0)
        self.assert_limit(self.plan())

    def test_relogin_does_not_reset_usage(self):
        for _ in range(3):
            self.assertEqual(self.plan()["code"], 0)
        account_service.logout(self.login["token"])
        login = account_service.login("quota_user", "quota-test-password")
        self.assert_limit(self.plan(headers={"Authorization": f"Bearer {login['token']}"}))

    def test_reopening_database_and_startup_do_not_reset_usage(self):
        for _ in range(3):
            self.assertEqual(self.plan()["code"], 0)
        reopened = create_engine(self.auth_url, connect_args={"check_same_thread": False})
        try:
            with patch.object(accounts, "engine", reopened):
                account_service.ensure_accounts()
                self.assert_limit(self.plan())
        finally:
            reopened.dispose()

    def test_password_demo_account_has_no_limit(self):
        demo = account_service.login(settings.AUTH_DEMO_USERNAME, "quota-test-password")
        demo_headers = {"Authorization": f"Bearer {demo['token']}"}
        for _ in range(5):
            self.assertEqual(self.plan(headers=demo_headers)["code"], 0)
            self.assertEqual(self.generate(headers=demo_headers)["code"], 0)

    def test_public_demo_keeps_its_read_only_permissions(self):
        demo = account_service.demo_login()
        demo_headers = {"Authorization": f"Bearer {demo['token']}"}
        self.assertEqual(self.plan(headers=demo_headers)["code"], 1007)
        self.assertEqual(self.generate(headers=demo_headers)["code"], 1007)
        self.planner.assert_not_called()
        self.generator.assert_not_called()

    def test_other_reads_and_writes_remain_unlimited_after_exhaustion(self):
        for _ in range(3):
            self.assertEqual(self.plan()["code"], 0)
            self.assertEqual(self.generate()["code"], 0)
        for index in range(5):
            created = self.client.post(
                "/api/trips", json={"title": f"自由整理旅行 {index}"}, headers=self.headers,
            ).json()
            self.assertEqual(created["code"], 0, created)
            for path in ("/api/trips", "/api/plans", "/api/reports", "/api/postcard-groups"):
                self.assertEqual(self.client.get(path, headers=self.headers).json()["code"], 0, path)

    def test_parallel_requests_cannot_consume_more_than_three_credits(self):
        start = Barrier(8)

        def consume(_):
            start.wait(timeout=10)
            try:
                with usage_service.reserve(self.user_id, "planning") as usage:
                    usage.consume()
                return True
            except UsageLimitError:
                return False

        with ThreadPoolExecutor(max_workers=8) as executor:
            accepted = list(executor.map(consume, range(8)))
        self.assertEqual(sum(accepted), 3)
        self.assert_limit(self.plan())

    def test_inflight_reservations_block_overbooking_and_release_on_failure(self):
        with ExitStack() as stack:
            for _ in range(3):
                stack.enter_context(usage_service.reserve(self.user_id, "planning"))
            self.assert_limit(self.plan())
        for _ in range(3):
            self.assertEqual(self.plan()["code"], 0)
        self.assert_limit(self.plan())

    def test_invalid_generation_options_do_not_consume_a_credit(self):
        self.assertEqual(self.generate(postcards=False, report=False)["code"], 1002)
        for _ in range(3):
            self.assertEqual(self.generate()["code"], 0)
        self.assert_limit(self.generate())

    def test_unknown_identity_cannot_reserve_credits(self):
        from app.core.exceptions import AuthenticationError

        with self.assertRaises(AuthenticationError):
            with usage_service.reserve("missing-user", "creation"):
                self.fail("Unknown identity was allowed")

    def test_finished_credits_are_not_released_by_repeated_cleanup(self):
        with usage_service.reserve(self.user_id, "planning") as usage:
            usage.consume()
            usage.consume()
        usage.release()
        for _ in range(2):
            self.assertEqual(self.plan()["code"], 0)
        self.assert_limit(self.plan())


if __name__ == "__main__":
    unittest.main()
