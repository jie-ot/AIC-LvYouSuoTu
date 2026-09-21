from __future__ import annotations

import io
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from PIL import Image
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.ai import orchestrator
from app.ai.memory.context_builder import build_photo_analysis_user_text
from app.ai.schemas import (
    PhotoAnalysisItem,
    PhotoAnalysisResult,
    PostcardPlanItem,
)
from app.api.endpoints.images import _read_upload_limited
from app.core.exceptions import AIGenerationError, InternalError, InvalidParamError
from app.models import dto, tables  # noqa: F401
from app.models.file_asset import FileAsset
from app.models.file_asset_reference import FileAssetReference
from app.models.generation_operation import GenerationOperation
from app.services import (
    file_asset_service,
    generation_service,
    image_service,
    memory_service,
    postcard_renderer,
    profile_engine,
    storage_service,
)


def _photo(asset_id: str, suitability: str = "good", tags: list[str] | None = None):
    return PhotoAnalysisItem(
        asset_id=asset_id,
        scene_summary="照片中可见湖畔与远山",
        observed_facts=["湖面", "远山"],
        scene_tags=tags or ["nature"],
        suitability=suitability,
        analysis_confidence=0.8,
    )


class GenerationHelpersTests(unittest.TestCase):
    def test_backend_count_parse_and_reduction(self) -> None:
        self.assertEqual(generation_service._parse_legacy_postcard_count("请做3张明信片"), 3)
        self.assertIsNone(generation_service._parse_legacy_postcard_count("我选了3张照片"))
        analysis = PhotoAnalysisResult(photos=[_photo("a"), _photo("b")])
        selection, reduced = generation_service._deterministic_selection(analysis, 5)
        self.assertTrue(reduced)
        self.assertEqual(len(selection.items), 2)

    def test_all_unsuitable_is_rejected(self) -> None:
        analysis = PhotoAnalysisResult(photos=[_photo("a", "unsuitable")])
        with self.assertRaises(AIGenerationError):
            generation_service._deterministic_selection(analysis, 1)

    def test_selection_prefers_scene_diversity(self) -> None:
        analysis = PhotoAnalysisResult(
            photos=[_photo("a", tags=["nature"]), _photo("b", tags=["nature"]), _photo("c", tags=["city"])]
        )
        selection, _ = generation_service._deterministic_selection(analysis, 2)
        ids = [item.source_asset_ids[0] for item in selection.items]
        self.assertIn("a", ids)
        self.assertIn("c", ids)

    def test_selection_respects_explicit_scene_preference(self) -> None:
        analysis = PhotoAnalysisResult(
            photos=[
                _photo("night", tags=["night", "city"]),
                _photo("coast", tags=["coast", "nature"]),
                _photo("culture", tags=["culture"]),
            ]
        )
        selection, _ = generation_service._deterministic_selection(
            analysis, 1, "优先海边，不要夜景",
        )
        self.assertEqual(selection.items[0].source_asset_ids, ["coast"])

    def test_selection_understands_natural_negative_scene_wording(self) -> None:
        analysis = PhotoAnalysisResult(
            photos=[
                _photo("night", tags=["night", "city"]),
                _photo("coast", tags=["coast", "nature"]),
            ]
        )
        selection, _ = generation_service._deterministic_selection(
            analysis, 1, "不喜欢夜景，优先海边",
        )
        self.assertEqual(selection.items[0].source_asset_ids, ["coast"])

    def test_selection_keeps_positive_half_after_unpunctuated_contrast(self) -> None:
        analysis = PhotoAnalysisResult(
            photos=[
                _photo("museum", tags=["culture"]),
                _photo("forest", tags=["nature"]),
            ]
        )
        selection, reduced = generation_service._deterministic_selection(
            analysis, 2, "不喜欢博物馆但是喜欢自然景观",
        )
        self.assertTrue(reduced)
        self.assertEqual(
            [item.source_asset_ids[0] for item in selection.items],
            ["forest"],
        )

    def test_selection_treats_dislike_and_hate_as_negative(self) -> None:
        analysis = PhotoAnalysisResult(
            photos=[
                _photo("night", tags=["night"]),
                _photo("coast", tags=["coast"]),
            ]
        )
        for wording in ("不爱夜景", "讨厌夜景"):
            with self.subTest(wording=wording):
                selection, _ = generation_service._deterministic_selection(
                    analysis, 1, wording,
                )
                self.assertEqual(selection.items[0].source_asset_ids, ["coast"])

    def test_selection_never_backfills_explicitly_excluded_scene(self) -> None:
        analysis = PhotoAnalysisResult(
            photos=[
                _photo("coast", tags=["coast"]),
                _photo("culture", tags=["culture"]),
                _photo("night", tags=["night"]),
            ]
        )
        selection, reduced = generation_service._deterministic_selection(
            analysis, 3, "不要夜景",
        )
        self.assertTrue(reduced)
        self.assertEqual(
            [item.source_asset_ids[0] for item in selection.items],
            ["coast", "culture"],
        )

    def test_selection_rejects_set_when_every_photo_is_explicitly_excluded(self) -> None:
        analysis = PhotoAnalysisResult(
            photos=[_photo("night-a", tags=["night"]), _photo("night-b", tags=["night"])],
        )
        with self.assertRaisesRegex(AIGenerationError, "明确要求避开"):
            generation_service._deterministic_selection(analysis, 2, "不喜欢夜景")

    def test_profile_low_sample_is_neutral_and_canonical(self) -> None:
        analysis = PhotoAnalysisResult(
            photos=[_photo("a")], overall_location="杭州", start_date="2026-09-01", end_date="2026-09-02"
        )
        report = profile_engine.build_profile(analysis, requirements="", memory_json={})
        traits = {item.id: item for item in report.profile_data.traits}
        for trait_id in ("environment", "depth", "planning", "social"):
            self.assertEqual(traits[trait_id].value, 50)
            self.assertEqual(traits[trait_id].assessment, "undetermined")
            self.assertEqual(traits[trait_id].evidence_refs, [])
        self.assertTrue(all(point.value == 50 for point in report.chart_data))
        self.assertEqual(report.profile_data.confidence, 0)
        self.assertEqual(report.profile_data.scene_signature.tokens, ["自然场景"])
        self.assertEqual(len(report.profile_data.next_trip_experiments), 2)
        self.assertEqual(report.location, "杭州")
        self.assertEqual(report.start_date, "2026-09-01")
        self.assertNotIn("朋友", report.content)

    def test_photo_food_is_scene_evidence_not_preference(self) -> None:
        analysis = PhotoAnalysisResult(
            photos=[_photo(f"f{index}", tags=["food"]) for index in range(3)]
        )
        report = profile_engine.build_profile(analysis, requirements="", memory_json={})
        chart = {item.dimension: item.value for item in report.chart_data}
        self.assertEqual(chart["美食偏好"], 50)
        self.assertIn("在地饮食", report.profile_data.scene_signature.tokens)

    def test_photo_culture_is_scene_evidence_not_radar_preference(self) -> None:
        analysis = PhotoAnalysisResult(
            photos=[_photo(f"c{index}", tags=["culture"]) for index in range(3)]
        )
        report = profile_engine.build_profile(analysis, requirements="", memory_json={})
        chart = {item.dimension: item.value for item in report.chart_data}
        self.assertEqual(chart["人文体验"], 50)
        self.assertIn("人文与历史", report.profile_data.scene_signature.tokens)

    def test_explicit_contrast_controls_radar_without_photo_reversal(self) -> None:
        analysis = PhotoAnalysisResult(
            photos=[_photo(f"m{index}", tags=["culture"]) for index in range(3)]
        )
        report = profile_engine.build_profile(
            analysis,
            requirements="不喜欢博物馆但是喜欢自然景观",
            memory_json={},
        )
        chart = {item.dimension: item.value for item in report.chart_data}
        self.assertLess(chart["人文体验"], 50)
        self.assertGreater(chart["自然探索"], 50)
        self.assertIn(
            "不喜欢博物馆但是喜欢自然景观",
            report.profile_data.explicit_requirements,
        )

    def test_single_legacy_memory_cannot_support_social_trait(self) -> None:
        analysis = PhotoAnalysisResult(
            photos=[_photo(f"p{index}") for index in range(3)]
        )
        report = profile_engine.build_profile(
            analysis,
            requirements="",
            memory_json={
                "preferences": [
                    {
                        "status": "active",
                        "summary": "喜欢和朋友结伴旅行",
                        "source_refs": ["one-old-report"],
                    }
                ]
            },
        )
        social = next(item for item in report.profile_data.traits if item.id == "social")
        self.assertEqual(social.value, 50)
        self.assertEqual(social.assessment, "undetermined")
        self.assertEqual(social.evidence_refs, [])

    def test_negated_requirements_do_not_reverse_trait_meaning(self) -> None:
        analysis = PhotoAnalysisResult(
            photos=[_photo(f"p{index}") for index in range(3)]
        )
        report = profile_engine.build_profile(
            analysis,
            requirements="不要详细计划，也不想一个人旅行，不和朋友结伴",
            memory_json={},
        )
        traits = {item.id: item for item in report.profile_data.traits}
        self.assertEqual(traits["planning"].assessment, "undetermined")
        self.assertEqual(traits["social"].assessment, "undetermined")

    def test_low_sample_keeps_explicit_request_without_scoring_it(self) -> None:
        analysis = PhotoAnalysisResult(photos=[_photo("a")])
        report = profile_engine.build_profile(
            analysis,
            requirements="我会和家人同行，请提前预订，但行程不要太赶",
            memory_json={},
        )
        self.assertTrue(all(item.value == 50 for item in report.profile_data.traits))
        self.assertIn("我会和家人同行", report.profile_data.explicit_requirements)
        self.assertIn("请提前预订", report.profile_data.explicit_requirements)
        self.assertIn("但行程不要太赶", report.profile_data.explicit_requirements)

    def test_low_sample_keeps_access_budget_food_lodging_and_transport_constraints(self) -> None:
        analysis = PhotoAnalysisResult(photos=[_photo("a")])
        report = profile_engine.build_profile(
            analysis,
            requirements=(
                "同行家人使用轮椅，酒店必须有电梯；"
                "不吃海鲜且对花生过敏；预算不超过3000元；"
                "交通优先高铁或驾车；明信片用暖色"
            ),
            memory_json={},
        )
        self.assertTrue(all(item.value == 50 for item in report.profile_data.traits))
        self.assertTrue(all(point.value == 50 for point in report.chart_data))
        self.assertEqual(
            report.profile_data.explicit_requirements,
            [
                "同行家人使用轮椅",
                "酒店必须有电梯",
                "不吃海鲜且对花生过敏",
                "预算不超过3000元",
                "交通优先高铁或驾车",
            ],
        )
        self.assertNotIn("明信片用暖色", report.profile_data.explicit_requirements)

    def test_accessibility_and_care_constraints_are_not_truncated(self) -> None:
        analysis = PhotoAnalysisResult(photos=[_photo("a")])
        report = profile_engine.build_profile(
            analysis,
            requirements=(
                "节奏要轻松；预算不超过3000元；交通优先高铁；"
                "酒店靠近地铁；不吃海鲜；同行老人使用轮椅；"
                "不能走楼梯；需要婴儿床"
            ),
            memory_json={},
        )
        self.assertTrue(all(item.value == 50 for item in report.profile_data.traits))
        self.assertEqual(len(report.profile_data.explicit_requirements), 8)
        self.assertIn("不能走楼梯", report.profile_data.explicit_requirements)
        self.assertIn("需要婴儿床", report.profile_data.explicit_requirements)

    def test_photo_analysis_context_never_injects_memory(self) -> None:
        text = build_photo_analysis_user_text(
            photo_metas=[{"asset_id": "a", "taken_at": None, "location": None}],
            requirements="生成报告",
            memory_summary="偏好海岸与慢节奏",
        )
        self.assertNotIn("用户长期旅行偏好摘要", text)
        self.assertNotIn("偏好海岸与慢节奏", text)

    def test_memory_proposal_cannot_flip_explicit_rejection_positive(self) -> None:
        filtered = generation_service._propose_memory_update(
            location="杭州",
            analysis=PhotoAnalysisResult(photos=[_photo("a")]),
            requirements="不喜欢博物馆，但喜欢自然景观",
        )
        self.assertEqual(filtered.add_preferences, ["不喜欢博物馆", "但喜欢自然景观"])
        self.assertLess(
            memory_service.preference_term_polarity(filtered.add_preferences[0], "博物馆"),
            0,
        )
        self.assertGreater(
            memory_service.preference_term_polarity(filtered.add_preferences[1], "自然景观"),
            0,
        )

    def test_postcard_prompt_rejects_rendered_copy_and_appends_hard_rule(self) -> None:
        item = PostcardPlanItem(
            design_concept="保留海岸原图的呼吸感和自然光线",
            photo_transformation="只进行轻微色彩平衡并保持人物与景物不变",
            visual_device="在画面中央添加大字标题形成视觉记忆点",
            typography="底图不渲染文字，标题由本地排版阶段处理",
            title="海岸呼吸",
            source_asset_ids=["a"],
            image_prompt="旅行明信片设计，保留原图场景与主体，只做克制的自然光影和色彩整理，不改变人物身份、动作或背景事实，保持真实的旅行现场感与安全留白。",
        )
        errors = orchestrator._postcard_plan_item_errors(item, ["a"])
        self.assertTrue(any("不得要求" in error for error in errors))
        prompt = orchestrator._compose_postcard_image_prompt(
            prompt="请添加邮戳和日期",
            design_concept="保留海岸原图的呼吸感和自然光线",
            photo_transformation="只进行轻微色彩平衡并保持人物与景物不变",
            visual_device="利用原图自然光线形成视觉重心",
            typography=item.typography,
            title=item.title,
            extra_texts=[],
        )
        self.assertNotIn("请添加邮戳和日期", prompt)
        self.assertTrue(prompt.endswith("保留原图主体与事实内容，只做克制的色彩、光线和构图整理。"))

    def test_local_fallback_is_decodable_with_safe_ratio(self) -> None:
        source = io.BytesIO()
        Image.new("RGB", (900, 1400), "#7393a7").save(source, format="JPEG")
        result = postcard_renderer.compose_postcard(source.getvalue(), "湖畔片刻", fallback=True)
        self.assertIn(result.render_mode, {"local_fallback", "local_no_text"})
        self.assertEqual(postcard_renderer.validate_postcard_bytes(result.content), (1500, 1000))

    def test_download_url_rejects_private_network(self) -> None:
        def private(*args, **kwargs):
            return [(2, 1, 6, "", ("127.0.0.1", 443))]

        with self.assertRaises(InternalError):
            storage_service._validate_public_download_url("https://img.volces.com/a.jpg", resolver=private)

        def public(*args, **kwargs):
            return [(2, 1, 6, "", ("8.8.8.8", 443))]

        self.assertEqual(
            storage_service._validate_public_download_url("https://img.volces.com/a.jpg", resolver=public),
            "https://img.volces.com/a.jpg",
        )

    def test_mime_and_upload_stream_limits(self) -> None:
        content = io.BytesIO()
        Image.new("RGB", (400, 400), "white").save(content, format="PNG")
        with self.assertRaises(InternalError):
            storage_service._validate_downloaded_image(content.getvalue(), "image/jpeg")
        with self.assertRaises(InvalidParamError):
            _read_upload_limited(io.BytesIO(b"1234"), max_bytes=3)


class PersistenceAndIdempotencyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
        SQLModel.metadata.create_all(self.engine)

        @contextmanager
        def scoped():
            with Session(self.engine) as session:
                try:
                    yield session
                    session.commit()
                except Exception:
                    session.rollback()
                    raise

        self.scoped = scoped

    def tearDown(self) -> None:
        self.engine.dispose()

    def test_strict_attach_rejects_foreign_asset(self) -> None:
        with Session(self.engine) as session:
            session.add(FileAsset(
                id="asset-1", user_id="other", relative_path="/static/uploads/x.jpg",
                mime_type="image/jpeg", size_bytes=10, usage_type="upload", status="temporary",
            ))
            session.commit()
            with self.assertRaises(InvalidParamError):
                file_asset_service.attach_with_reference(
                    session, asset_id="asset-1", user_id="me", owner_type="report",
                    owner_id="r1", role="source_photo",
                )

    def test_idempotency_replays_same_payload_and_conflicts_on_change(self) -> None:
        request = dto.GenerateRequest(
            photos=[dto.UploadedPhoto(asset_id="a", image_url="/static/uploads/a.jpg", taken_at=None, location=None)],
            requirements="x",
            options=dto.GenerateOptions(generate_postcards=True, generate_report=False),
            client_request_id="request-123",
        )
        with patch.object(generation_service, "session_scope", self.scoped):
            operation_id, replay, _ = generation_service._begin_operation("u", request)
            self.assertIsNone(replay)
            with self.scoped() as session:
                operation = session.get(GenerationOperation, operation_id)
                result = dto.GenerateResult(
                    postcard_group=None, report=None, operation_id=operation_id,
                    postcard_status="failed", status="partial",
                )
                operation.status = "partial"
                operation.response_json = result.model_dump(mode="json", by_alias=True)
                session.add(operation)
            replay_id, replay, _ = generation_service._begin_operation("u", request)
            self.assertEqual(replay_id, operation_id)
            self.assertEqual(replay.status, "partial")
            changed = request.model_copy(update={"requirements": "changed"})
            with self.assertRaises(InvalidParamError):
                generation_service._begin_operation("u", changed)

    def test_failed_operation_allows_controlled_retry_with_same_identity(self) -> None:
        request = dto.GenerateRequest(
            photos=[
                dto.UploadedPhoto(
                    asset_id="a", image_url="/static/uploads/a.jpg",
                    taken_at=None, location=None,
                )
            ],
            requirements="原样重试",
            options=dto.GenerateOptions(generate_postcards=True, generate_report=False),
            client_request_id="request-failed-retry",
        )
        with patch.object(generation_service, "session_scope", self.scoped):
            operation_id, _, _ = generation_service._begin_operation("u", request)
            with self.scoped() as session:
                operation = session.get(GenerationOperation, operation_id)
                operation.status = "failed"
                operation.postcard_status = "failed"
                operation.error_message = "provider timeout"
                operation.response_json = {"stale": True}
                operation.pending_memory_payload = {"stale": True}
                session.add(operation)
            retried_id, replay, pending = generation_service._begin_operation("u", request)
            self.assertEqual(retried_id, operation_id)
            self.assertIsNone(replay)
            self.assertIsNone(pending)
            with self.scoped() as session:
                retried = session.get(GenerationOperation, operation_id)
                state = (
                    retried.status,
                    retried.postcard_status,
                    retried.report_status,
                    retried.memory_status,
                    retried.response_json,
                    retried.pending_memory_payload,
                    retried.error_message,
                )
        self.assertEqual(
            state,
            ("processing", "skipped", "skipped", "skipped", None, None, None),
        )

    def test_partial_replay_retries_only_pending_memory_and_clears_stale_warning(self) -> None:
        request = dto.GenerateRequest(
            photos=[
                dto.UploadedPhoto(
                    asset_id="a", image_url="/static/uploads/a.jpg",
                    taken_at=None, location=None,
                )
            ],
            requirements="生成旅行偏好报告",
            options=dto.GenerateOptions(
                generate_postcards=False,
                generate_report=True,
                learn_preferences=True,
            ),
            client_request_id="request-memory-replay",
        )
        with patch.object(generation_service, "session_scope", self.scoped):
            operation_id, _, _ = generation_service._begin_operation("u", request)
            stale_warning = dto.GenerationWarning(
                code="MEMORY_MERGE_FAILED",
                message="作品已保存，但本次观察未写入旅行记忆",
                feature="memory",
                retryable=True,
            )
            stored_result = dto.GenerateResult(
                postcard_group=None,
                report=None,
                operation_id=operation_id,
                status="partial",
                postcard_status="skipped",
                report_status="success",
                memory_status="failed",
                warnings=[stale_warning],
            )
            with self.scoped() as session:
                operation = session.get(GenerationOperation, operation_id)
                operation.status = "partial"
                operation.postcard_status = "skipped"
                operation.report_status = "success"
                operation.memory_status = "failed"
                operation.pending_memory_payload = {
                    "add_preferences": ["偏好自然景观与开阔空间"],
                    "confidence": 0.4,
                    "trip_fingerprint": "trip-a",
                }
                operation.response_json = stored_result.model_dump(mode="json", by_alias=True)
                session.add(operation)
            with (
                patch.object(generation_service, "_merge_pending_memory", return_value="success") as merge,
                patch.object(
                    generation_service.orchestrator,
                    "analyze_photos",
                    side_effect=AssertionError("provider must not run during replay"),
                ),
            ):
                replayed = generation_service.generate("u", request)
        self.assertEqual(replayed.status, "completed")
        self.assertEqual(replayed.memory_status, "success")
        self.assertEqual(replayed.warnings, [])
        merge.assert_called_once()

    def test_memory_proposal_is_deterministic_and_replay_does_not_recreate_report(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp_root:
            upload_dir = Path(temp_root) / "uploads"
            upload_dir.mkdir(parents=True)
            image = io.BytesIO()
            Image.new("RGB", (640, 480), "#6f91a5").save(image, format="JPEG")
            content = image.getvalue()
            (upload_dir / "nature.jpg").write_bytes(content)
            with self.scoped() as session:
                session.add(FileAsset(
                    id="nature",
                    user_id="u",
                    relative_path="/static/uploads/nature.jpg",
                    mime_type="image/jpeg",
                    size_bytes=len(content),
                    usage_type="upload",
                    status="temporary",
                ))
            request = dto.GenerateRequest(
                photos=[
                    dto.UploadedPhoto(
                        asset_id="nature",
                        image_url="/static/uploads/nature.jpg",
                        taken_at=None,
                        location=None,
                    )
                ],
                requirements="喜欢自然景观",
                options=dto.GenerateOptions(
                    generate_postcards=False,
                    generate_report=True,
                    learn_preferences=True,
                ),
                client_request_id="request-proposal-retry",
            )
            analysis = PhotoAnalysisResult(
                photos=[_photo("nature", tags=["nature"])],
                overall_location="杭州",
            )
            with (
                patch.object(generation_service, "session_scope", self.scoped),
                patch.object(generation_service.settings, "STATIC_ROOT", temp_root),
                patch.object(
                    generation_service.orchestrator,
                    "analyze_photos",
                    return_value=analysis,
                ) as analyze,
                patch.object(
                    generation_service.orchestrator,
                    "propose_memory_update",
                    side_effect=RuntimeError("must not be called"),
                ) as propose,
            ):
                first = generation_service.generate("u", request)
                first_report_id = first.report.id
                self.assertEqual(first.status, "completed")
                self.assertEqual(first.memory_status, "success")
                self.assertFalse([w for w in first.warnings if w.feature == "memory"])
                with self.scoped() as session:
                    operation = session.get(GenerationOperation, first.operation_id)
                    self.assertIsNone(operation.pending_memory_payload)

                replayed = generation_service.generate("u", request)

            self.assertEqual(replayed.status, "completed")
            self.assertEqual(replayed.memory_status, "success")
            self.assertEqual(replayed.report.id, first_report_id)
            self.assertFalse([w for w in replayed.warnings if w.feature == "memory"])
            self.assertEqual(analyze.call_count, 1)
            self.assertEqual(propose.call_count, 0)
            with self.scoped() as session:
                operation = session.get(GenerationOperation, first.operation_id)
                self.assertIsNone(operation.pending_memory_payload)

    def test_persist_branch_failure_returns_partial_with_sibling(self) -> None:
        analysis = PhotoAnalysisResult(photos=[_photo("a")], overall_location="杭州")
        report_draft = profile_engine.build_profile(analysis, requirements="", memory_json={})
        operation = GenerationOperation(
            id="genop-1", user_id="u", client_request_id="req-partial",
            request_hash="hash", status="processing",
        )
        with self.scoped() as session:
            session.add(operation)
        report_dto = dto.Report(
            id="r", location="杭州", start_date=None, end_date=None,
            date_label="", cover_image="/static/uploads/a.jpg",
            personality_summary="样本待积累", content="证据有限",
            chart_data=[], profile_version=3, profile_data=report_draft.profile_data,
        )
        render = generation_service.PostcardRender(
            title="湖畔片刻", relative_path="/static/generated/postcards/x.jpg",
            sort_order=0, asset_id="missing", source_asset_ids=["a"], render_mode="local_fallback",
        )
        options = dto.GenerateOptions(generate_postcards=True, generate_report=True)
        with (
            patch.object(generation_service, "session_scope", self.scoped),
            patch.object(generation_service, "_persist_postcard_branch", side_effect=RuntimeError("boom")),
            patch.object(generation_service, "_persist_report_branch", return_value=report_dto),
            patch.object(generation_service, "_discard"),
        ):
            result = generation_service._persist_results(
                user_id="u", operation_id="genop-1", options=options,
                location="杭州", date_label="", start_date=None, end_date=None,
                source_asset_ids=["a"], postcard_renders=[render],
                report_draft=report_draft, report_cover_source_id="a",
                postcard_status="success", report_status="success", memory_status="skipped",
                warnings=[], pending_memory_payload=None,
            )
        self.assertEqual(result.status, "partial")
        self.assertEqual(result.postcard_status, "failed")
        self.assertEqual(result.report_status, "success")
        self.assertIsNotNone(result.report)

    def test_generate_report_uses_detached_safe_snapshot_and_excludes_unsuitable(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp_root:
            upload_dir = Path(temp_root) / "uploads"
            upload_dir.mkdir(parents=True)
            good_image = io.BytesIO()
            private_image = io.BytesIO()
            Image.new("RGB", (640, 480), "#6f91a5").save(good_image, format="JPEG")
            Image.new("RGB", (640, 480), "#a56f79").save(private_image, format="JPEG")
            contents = {"good.jpg": good_image.getvalue(), "private.jpg": private_image.getvalue()}
            for name, content in contents.items():
                (upload_dir / name).write_bytes(content)
            with self.scoped() as session:
                for asset_id, name in (("good", "good.jpg"), ("private", "private.jpg")):
                    session.add(FileAsset(
                        id=asset_id, user_id="u", relative_path=f"/static/uploads/{name}",
                        mime_type="image/jpeg", size_bytes=len(contents[name]), usage_type="upload",
                        status="temporary",
                    ))
            analysis = PhotoAnalysisResult(
                photos=[_photo("good"), _photo("private", suitability="unsuitable")],
                overall_location="杭州",
            )
            request = dto.GenerateRequest(
                photos=[
                    dto.UploadedPhoto(asset_id="good", image_url="/static/uploads/good.jpg", taken_at=None, location=None),
                    dto.UploadedPhoto(asset_id="private", image_url="/static/uploads/private.jpg", taken_at=None, location=None),
                ],
                requirements="生成旅行偏好观察",
                options=dto.GenerateOptions(generate_postcards=False, generate_report=True),
                client_request_id="request-main-flow",
            )
            with (
                patch.object(generation_service, "session_scope", self.scoped),
                patch.object(generation_service.settings, "STATIC_ROOT", temp_root),
                patch.object(generation_service.orchestrator, "analyze_photos", return_value=analysis),
            ):
                result = generation_service.generate("u", request)
            self.assertEqual(result.status, "completed")
            self.assertIsNotNone(result.report)
            self.assertEqual(
                result.report.profile_data.evidence_highlights[0].image_url,
                "/static/uploads/good.jpg",
            )
            with self.scoped() as session:
                referenced_ids = [
                    ref.asset_id for ref in session.exec(select(FileAssetReference)).all()
                ]
            self.assertIn("good", referenced_ids)
            self.assertNotIn("private", referenced_ids)

    def test_generate_preserves_actionable_all_scenes_excluded_message(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp_root:
            upload_dir = Path(temp_root) / "uploads"
            upload_dir.mkdir(parents=True)
            image = io.BytesIO()
            Image.new("RGB", (640, 480), "#17263b").save(image, format="JPEG")
            content = image.getvalue()
            (upload_dir / "night.jpg").write_bytes(content)
            with self.scoped() as session:
                session.add(FileAsset(
                    id="night",
                    user_id="u",
                    relative_path="/static/uploads/night.jpg",
                    mime_type="image/jpeg",
                    size_bytes=len(content),
                    usage_type="upload",
                    status="temporary",
                ))
            request = dto.GenerateRequest(
                photos=[
                    dto.UploadedPhoto(
                        asset_id="night",
                        image_url="/static/uploads/night.jpg",
                        taken_at=None,
                        location=None,
                    )
                ],
                requirements="不喜欢夜景",
                options=dto.GenerateOptions(
                    generate_postcards=True,
                    generate_report=False,
                    postcard_count=1,
                ),
                client_request_id="request-all-scenes-excluded",
            )
            analysis = PhotoAnalysisResult(
                photos=[_photo("night", tags=["night"])],
                overall_location="未知目的地",
            )
            with (
                patch.object(generation_service, "session_scope", self.scoped),
                patch.object(generation_service.settings, "STATIC_ROOT", temp_root),
                patch.object(
                    generation_service.orchestrator,
                    "analyze_photos",
                    return_value=analysis,
                ),
            ):
                with self.assertRaisesRegex(
                    AIGenerationError,
                    "请调整要求或更换照片",
                ):
                    generation_service.generate("u", request)

    def test_trip_fingerprint_distinguishes_metadata_free_asset_sets(self) -> None:
        first = PhotoAnalysisResult(photos=[_photo("a")])
        repeated = PhotoAnalysisResult(photos=[_photo("a")])
        second = PhotoAnalysisResult(photos=[_photo("b")])
        self.assertEqual(generation_service._trip_fingerprint(first), generation_service._trip_fingerprint(repeated))
        self.assertNotEqual(generation_service._trip_fingerprint(first), generation_service._trip_fingerprint(second))
        self.assertEqual(
            generation_service._trip_fingerprint(first, {"a": "same-content"}),
            generation_service._trip_fingerprint(second, {"b": "same-content"}),
        )
        self.assertNotEqual(
            generation_service._trip_fingerprint(first, {"a": "first-content"}),
            generation_service._trip_fingerprint(second, {"b": "second-content"}),
        )

    def test_same_content_with_different_asset_ids_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp_root:
            upload_dir = Path(temp_root) / "uploads"
            upload_dir.mkdir(parents=True)
            image = io.BytesIO()
            Image.new("RGB", (320, 240), "#7894aa").save(image, format="JPEG")
            content = image.getvalue()
            (upload_dir / "first.jpg").write_bytes(content)
            (upload_dir / "second.jpg").write_bytes(content)
            with self.scoped() as session:
                for asset_id, name in (("first", "first.jpg"), ("second", "second.jpg")):
                    session.add(FileAsset(
                        id=asset_id,
                        user_id="u",
                        relative_path=f"/static/uploads/{name}",
                        mime_type="image/jpeg",
                        size_bytes=len(content),
                        usage_type="upload",
                        status="temporary",
                    ))
            photos = [
                dto.UploadedPhoto(
                    asset_id="first", image_url="/static/uploads/first.jpg",
                    taken_at=None, location=None,
                ),
                dto.UploadedPhoto(
                    asset_id="second", image_url="/static/uploads/second.jpg",
                    taken_at=None, location=None,
                ),
            ]
            with patch.object(generation_service.settings, "STATIC_ROOT", temp_root):
                with self.scoped() as session:
                    with self.assertRaisesRegex(InvalidParamError, "内容相同"):
                        generation_service._validate_and_load_photos(session, "u", photos)

    def test_upload_reuses_existing_asset_for_identical_normalized_content(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp_root:
            image = io.BytesIO()
            Image.new("RGB", (320, 240), "#7894aa").save(image, format="JPEG")
            content = image.getvalue()
            with (
                patch.object(image_service, "session_scope", self.scoped),
                patch.object(storage_service.settings, "STATIC_ROOT", temp_root),
            ):
                first = image_service.save_uploaded_image("u", content, "first.jpg", "image/jpeg")
                second = image_service.save_uploaded_image("u", content, "renamed.jpg", "image/jpeg")
            self.assertEqual(first.asset_id, second.asset_id)
            self.assertEqual(first.image_url, second.image_url)
            with self.scoped() as session:
                assets = session.exec(select(FileAsset)).all()
                checksums = [asset.checksum for asset in assets]
            self.assertEqual(len(assets), 1)
            self.assertIsNotNone(checksums[0])

    def test_upload_backfills_and_reuses_legacy_null_checksum_asset(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp_root:
            image = io.BytesIO()
            Image.new("RGB", (320, 240), "#6789ab").save(image, format="JPEG")
            content = image.getvalue()
            with patch.object(storage_service.settings, "STATIC_ROOT", temp_root):
                legacy_file = storage_service.save_upload(
                    content, "legacy.jpg", "image/jpeg",
                )
                with self.scoped() as session:
                    session.add(FileAsset(
                        id="legacy-null-checksum",
                        user_id="u",
                        relative_path=legacy_file.relative_path,
                        mime_type=legacy_file.mime_type,
                        size_bytes=legacy_file.size_bytes,
                        usage_type="upload",
                        status="attached",
                        checksum=None,
                    ))
                with patch.object(image_service, "session_scope", self.scoped):
                    uploaded = image_service.save_uploaded_image(
                        "u", content, "same-photo.jpg", "image/jpeg",
                    )
            self.assertEqual(uploaded.asset_id, "legacy-null-checksum")
            with self.scoped() as session:
                assets = session.exec(select(FileAsset)).all()
                self.assertEqual(len(assets), 1)
                self.assertIsNotNone(assets[0].checksum)


if __name__ == "__main__":
    unittest.main()
