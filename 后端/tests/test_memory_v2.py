from __future__ import annotations

import unittest

from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.core.exceptions import InvalidParamError
from app.models import tables  # noqa: F401
from app.models.user_memory_event import UserMemoryEvent
from app.services import memory_service
from app.services.memory_display_adapter import MemoryDisplayAdapter


class MemoryV3ContractTests(unittest.TestCase):
    """Regression coverage for concrete, user-controlled travel memory."""

    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
        SQLModel.metadata.create_all(self.engine)
        self.session = Session(self.engine)

    def tearDown(self) -> None:
        self.session.close()
        self.engine.dispose()

    def _current(self, user_id: str = "user-1"):
        return memory_service.get_or_create_current_memory(self.session, user_id)

    def test_photo_observations_never_become_memory(self) -> None:
        memory = self._current()
        version = memory.version
        for index in range(2):
            memory = memory_service.merge_memory_update(
                self.session,
                user_id="user-1",
                add_preferences=["偏好自然景观和开阔空间"],
                weaken_preferences=[],
                evidence_summary="",
                confidence=0.9,
                source_type="generate",
                source_id=f"op-{index}",
                trip_fingerprint=f"trip-{index}",
            )
        self.assertEqual(memory.version, version)
        self.assertEqual(memory.memory_json["items"], [])
        self.assertEqual(self.session.exec(select(UserMemoryEvent)).all(), [])

    def test_only_concrete_explicit_requirements_are_suggested(self) -> None:
        memory = self._current("explicit")
        memory = memory_service.merge_memory_update(
            self.session,
            user_id="explicit",
            add_preferences=["酒店要安静，步行十分钟内到地铁", "喜欢旅行中的光影"],
            weaken_preferences=[],
            evidence_summary="",
            confidence=1,
            source_type="explicit_requirement",
            source_id="requirements-1",
            trip_fingerprint="trip-1",
        )
        self.assertEqual(len(memory.memory_json["items"]), 1)
        item = memory.memory_json["items"][0]
        self.assertEqual(item["text"], "酒店要安静，步行十分钟内到地铁")
        self.assertEqual(item["state"], "suggested")
        self.assertFalse(item["enabled"])
        self.assertEqual(memory_service.build_memory_summary(memory), "")

        display_item = MemoryDisplayAdapter().to_display(memory).memories[0]
        self.assertEqual(display_item.state, "candidate")
        confirmed = memory_service.patch_memory_item(
            self.session,
            user_id="explicit",
            item_id=item["id"],
            confirm=True,
            expected_version=memory.version,
        )
        self.assertIn("酒店要安静", memory_service.build_memory_summary(confirmed))

    def test_common_concrete_requests_are_not_lost(self) -> None:
        for text in ("只住亚朵", "带狗", "自驾要有充电桩", "不要网红店"):
            with self.subTest(text=text):
                self.assertTrue(memory_service.is_actionable_requirement(text))
        for text in ("喜欢旅行中的光影", "明信片保留自然色调", "画面要有氛围感"):
            with self.subTest(text=text):
                self.assertFalse(memory_service.is_actionable_requirement(text))

    def test_manual_memory_preserves_exact_text_and_category(self) -> None:
        memory = self._current("manual")
        memory = memory_service.add_memory_item(
            self.session,
            user_id="manual",
            text="不喜欢博物馆和历史街区",
            category="attractions",
            expected_version=memory.version,
        )
        item = memory.memory_json["items"][0]
        self.assertEqual(item["text"], "不喜欢博物馆和历史街区")
        self.assertEqual(item["category"], "attractions")
        self.assertEqual(item["state"], "saved")
        self.assertTrue(item["enabled"])

    def test_user_can_edit_toggle_and_delete_an_item(self) -> None:
        memory = self._current("controls")
        memory = memory_service.add_memory_item(
            self.session,
            user_id="controls",
            text="每晚住宿预算不超过 600 元",
            category="budget",
            expected_version=memory.version,
        )
        item_id = memory.memory_json["items"][0]["id"]
        memory = memory_service.patch_memory_item(
            self.session,
            user_id="controls",
            item_id=item_id,
            text="每晚住宿预算不超过 800 元",
            category="budget",
            enabled=False,
            expected_version=memory.version,
        )
        item = memory.memory_json["items"][0]
        self.assertEqual(item["text"], "每晚住宿预算不超过 800 元")
        self.assertFalse(item["enabled"])
        self.assertEqual(memory_service.build_memory_summary(memory), "")

        memory = memory_service.delete_memory_item(
            self.session,
            user_id="controls",
            item_id=item_id,
            expected_version=memory.version,
        )
        self.assertEqual(memory.memory_json["items"], [])
        self.assertEqual(MemoryDisplayAdapter().to_display(memory).memories, [])

    def test_global_switch_controls_planning_context(self) -> None:
        memory = self._current("settings")
        memory = memory_service.add_memory_item(
            self.session,
            user_id="settings",
            text="只坐高铁，不接受夜间换乘",
            category="transport",
            expected_version=memory.version,
        )
        self.assertIn("只坐高铁", memory_service.build_memory_summary(memory))
        memory = memory_service.set_memory_enabled(
            self.session,
            user_id="settings",
            enabled=False,
            expected_version=memory.version,
        )
        self.assertEqual(memory_service.build_memory_summary(memory), "")
        self.assertFalse(MemoryDisplayAdapter().to_display(memory).enabled)

    def test_legacy_upgrade_keeps_only_concrete_manual_memory(self) -> None:
        memory = self._current("legacy")
        memory.memory_json = {
            "schema_version": 2,
            "preferences": [
                {
                    "preference_id": "manual-hotel",
                    "summary": "酒店要安静",
                    "category": "hotel",
                    "state": "active",
                    "origin": "manual",
                },
                {
                    "preference_id": "inferred-photo",
                    "summary": "偏好自然景观与开阔空间",
                    "category": "attractions",
                    "state": "active",
                    "origin": "inferred",
                },
                {"summary": "ƫ���ƫ���", "state": "active", "origin": "manual"},
            ],
            "tombstones": [],
        }
        self.session.add(memory)
        self.session.flush()

        display = MemoryDisplayAdapter().to_display(memory)
        self.assertEqual([item.content for item in display.memories], ["酒店要安静"])
        self.assertEqual(display.legacy_count, 2)
        summary = memory_service.build_memory_summary(memory)
        self.assertIn("酒店要安静", summary)
        self.assertNotIn("自然景观", summary)
        self.assertNotIn("�", summary)

    def test_contrast_and_negative_helpers_remain_correct(self) -> None:
        self.assertEqual(
            memory_service.negated_taxonomy_keys("不喜欢博物馆但是喜欢自然景观"),
            {"culture.local"},
        )
        self.assertIsNone(
            memory_service.canonicalize("不喜欢自然景观和开阔空间", reject_negated=True)
        )

    def test_stale_version_has_a_clear_error(self) -> None:
        self._current("stale")
        with self.assertRaisesRegex(InvalidParamError, "刷新"):
            memory_service.set_memory_enabled(
                self.session,
                user_id="stale",
                enabled=False,
                expected_version=99,
            )


if __name__ == "__main__":
    unittest.main()
