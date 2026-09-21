"""Confirmation checklist must carry residual requirements into generation."""

from __future__ import annotations

from unittest import TestCase

from app.models.dto import PlanningBrief
from app.services import planning_intake_service


class DetailRequirementsTest(TestCase):
    def test_checklist_ends_with_detail_requirements(self) -> None:
        brief = planning_intake_service.finalize_brief(
            PlanningBrief(
                origin="南京",
                destinations=["丹东", "大连"],
                start_date="2026-08-07",
                end_date="2026-08-11",
                detail_requirements="8月11号晚上回南京；丹东玩到8月8号傍晚再去大连",
            )
        )
        checklist = planning_intake_service.build_checklist(brief)

        self.assertEqual(checklist[-1].key, "detailRequirements")
        self.assertEqual(checklist[-1].label, "详细需求")
        self.assertEqual(
            checklist[-1].value,
            "8月11号晚上回南京；丹东玩到8月8号傍晚再去大连",
        )
        self.assertEqual(checklist[-1].status, "ready")

    def test_confirmed_text_includes_detail_requirements_and_checklist_marker(self) -> None:
        brief = planning_intake_service.finalize_brief(
            PlanningBrief(
                origin="乌鲁木齐",
                destinations=["喀纳斯"],
                start_date="2026-08-20",
                end_date="2026-08-26",
                detail_requirements="第一天下午到达，尽量少赶路",
            )
        )

        text = planning_intake_service.confirmed_requirement_text(
            brief, "这份确认清单无误，请开始生成行程。"
        )

        self.assertIn("【确认清单】", text)
        self.assertIn("详细需求：第一天下午到达，尽量少赶路", text)

    def test_model_text_is_kept_as_is_without_chat_or_assumption_dump(self) -> None:
        brief = planning_intake_service.finalize_brief(
            PlanningBrief(
                origin="南京",
                destinations=["三亚"],
                start_date="2026-08-09",
                end_date="2026-08-13",
                detail_requirements=(
                    "8月9日上午出发，8月13日晚上返回；行程节奏偏慢；"
                    "喜欢沙滩，希望安排一次浮潜。"
                ),
                assumptions=["默认2人出行", "行程节奏偏慢", "偏好住宿在海边或市区，待确认"],
            ),
            user_messages=[
                "这个季节我想去海南三亚玩一玩，大概五六天吧，你觉得怎么样？",
                "我打算8月9号上午从南京出发，就玩5天吧，13号晚上回来",
            ],
        )

        self.assertEqual(
            brief.detail_requirements,
            "8月9日上午出发，8月13日晚上返回；行程节奏偏慢；喜欢沙滩，希望安排一次浮潜。",
        )
        self.assertNotIn("暂定理解", brief.detail_requirements)
        self.assertNotIn("这个季节我想去", brief.detail_requirements)

    def test_blank_detail_becomes_wu(self) -> None:
        brief = planning_intake_service.finalize_brief(
            PlanningBrief(
                origin="上海",
                destinations=["杭州"],
                start_date="2026-09-01",
                end_date="2026-09-03",
                transport_preference="高铁往返",
                constraints=["不要早于10点出发"],
            )
        )

        self.assertEqual(brief.detail_requirements, "无")
        item = planning_intake_service.build_checklist(brief)[-1]
        self.assertEqual(item.value, "无")
        self.assertEqual(item.status, "assumed")

    def test_placeholder_strings_also_become_wu(self) -> None:
        brief = planning_intake_service.finalize_brief(
            PlanningBrief(
                origin="北京",
                destinations=["天津"],
                start_date="2026-10-01",
                end_date="2026-10-02",
                detail_requirements="暂无额外说明",
            )
        )
        self.assertEqual(brief.detail_requirements, "无")
