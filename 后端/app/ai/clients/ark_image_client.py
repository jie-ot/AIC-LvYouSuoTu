"""Ark OpenAI-compatible images/generations client.

Uses the Agent Plan image generation endpoint and its dedicated API key.
Reference images make the call image-to-image; omitting them is text-to-image.
Temporary data[0].url is handed to storage_service.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass

import httpx

from app.core.business_logging import log_event
from app.core.config import settings
from app.core.exceptions import AIGenerationError, ImageInputPolicyError, InternalError

logger = logging.getLogger("lvyousuotu")


@dataclass
class ImageGenerationResult:
    """Remote temp image URL returned by the model gateway."""

    image_url: str | None = None
    ext: str = "jpg"


def generate_image(
    *,
    prompt: str,
    image_data_urls: list[str] | None = None,
    size: str | None = None,
    max_attempts: int | None = None,
) -> ImageGenerationResult:
    """Generate one image. Reference images are optional (text-to-image)."""
    if not settings.ARK_PLAN_API_KEY:
        raise InternalError("图片模型服务未配置 ARK_PLAN_API_KEY（Agent Plan 专属 API Key）")
    return _real_generate_image(
        prompt=prompt,
        image_data_urls=image_data_urls or [],
        size=size or settings.ARK_IMAGE_SIZE,
        max_attempts=max_attempts,
    )


def _real_generate_image(
    *,
    prompt: str,
    image_data_urls: list[str],
    size: str,
    max_attempts: int | None = None,
) -> ImageGenerationResult:
    """POST the OpenAI-compatible JSON body and return the first image URL."""
    if len(image_data_urls) > 10:
        raise AIGenerationError("AI 生成失败：Seedream 5.0 pro 最多支持 10 张参考图")

    # A HTTP-200 response without a usable image is a transient gateway result
    # in practice. Always allow one retry for that case even when the generic
    # retry setting is disabled. Callers that must not regenerate pass
    # max_attempts=1.
    attempts = (
        max(1, max_attempts)
        if max_attempts is not None
        else max(2, settings.MODEL_MAX_RETRY + 1)
    )
    last_transient: Exception | None = None
    body: dict[str, object] = {
        "model": settings.ARK_IMAGE_MODEL,
        "prompt": prompt,
        "size": size,
        "response_format": "url",
        "output_format": "jpeg",
        "watermark": False,
        # Each request asks for one image; no group-generation options.
    }
    if image_data_urls:
        body["image"] = image_data_urls if len(image_data_urls) > 1 else image_data_urls[0]

    for attempt in range(attempts):
        request_id = str(uuid.uuid4())
        headers = {
            "Authorization": f"Bearer {settings.ARK_PLAN_API_KEY}",
            "Content-Type": "application/json; charset=utf-8",
        }
        started = time.monotonic()
        try:
            with httpx.Client(timeout=settings.ARK_IMAGE_TIMEOUT_SECONDS) as client:
                resp = client.post(
                    f"{settings.ARK_PLAN_BASE_URL.rstrip('/')}/images/generations",
                    headers=headers,
                    json=body,
                )
        except (httpx.TimeoutException, httpx.ConnectError, httpx.ReadError) as exc:
            last_transient = exc
            logger.warning(
                "ark image transient error (request_id=%s, attempt=%d/%d): %s",
                request_id, attempt + 1, attempts, type(exc).__name__,
            )
            log_event(
                "ark_image",
                status="retry",
                request_id=request_id,
                attempt=attempt + 1,
                attempts=attempts,
                reason=type(exc).__name__,
            )
            _sleep_before_retry(attempt, attempts)
            continue
        except Exception as exc:  # noqa: BLE001
            logger.exception("ark image unexpected error (request_id=%s)", request_id)
            log_event(
                "ark_image",
                status="failed",
                request_id=request_id,
                attempt=attempt + 1,
                reason=type(exc).__name__,
            )
            raise InternalError("图片模型服务内部错误") from exc

        if resp.status_code in (401, 403):
            logger.error("ark image auth/permission error (request_id=%s)", request_id)
            log_event(
                "ark_image",
                status="failed",
                request_id=request_id,
                attempt=attempt + 1,
                reason="auth_or_permission",
                http_status=resp.status_code,
            )
            raise InternalError("图片模型服务鉴权或权限错误")
        if resp.status_code == 429:
            last_transient = httpx.HTTPStatusError("rate limited", request=resp.request, response=resp)
            logger.warning("ark image rate limited (request_id=%s)", request_id)
            log_event(
                "ark_image",
                status="retry",
                request_id=request_id,
                attempt=attempt + 1,
                attempts=attempts,
                reason="rate_limited",
                http_status=resp.status_code,
            )
            _sleep_before_retry(attempt, attempts)
            continue
        if resp.status_code >= 500:
            last_transient = httpx.HTTPStatusError("5xx", request=resp.request, response=resp)
            logger.warning("ark image 5xx (request_id=%s)", request_id)
            log_event(
                "ark_image",
                status="retry",
                request_id=request_id,
                attempt=attempt + 1,
                attempts=attempts,
                reason="server_error",
                http_status=resp.status_code,
            )
            _sleep_before_retry(attempt, attempts)
            continue
        try:
            payload = resp.json()
            empty_reason = "empty_image"
        except ValueError:
            payload = None
            empty_reason = "invalid_json"

        # Ark uses HTTP 400 + error.code for input-policy rejection.
        policy_codes = _input_policy_codes(payload)
        if policy_codes:
            provider_code = policy_codes[0]
            input_kind = (
                "image"
                if provider_code.startswith("InputImage")
                else "text"
                if provider_code.startswith("InputText")
                else "unknown"
            )
            log_event(
                "ark_image",
                status="rejected",
                request_id=request_id,
                attempt=attempt + 1,
                reason=f"{input_kind}_input_policy_violation",
                http_status=resp.status_code,
                response_summary=_summarize_response(payload, resp),
            )
            raise ImageInputPolicyError(
                "图片模型输入内容审核未通过",
                input_kind=input_kind,
                provider_code=provider_code,
            )

        if resp.status_code != 200:
            response_summary = _summarize_response(payload, resp)
            logger.warning(
                "ark image bad request (request_id=%s status=%d summary=%s)",
                request_id,
                resp.status_code,
                response_summary,
            )
            log_event(
                "ark_image",
                status="failed",
                request_id=request_id,
                attempt=attempt + 1,
                reason="bad_status",
                http_status=resp.status_code,
                response_summary=response_summary,
            )
            raise AIGenerationError("AI 生成失败：图片模型返回错误")

        latency_ms = int((time.monotonic() - started) * 1000)
        image_url = _extract_image_url(payload)
        if not image_url:
            response_summary = _summarize_response(payload, resp)
            if _provider_errors(payload):
                log_event(
                    "ark_image", status="failed", request_id=request_id,
                    reason="provider_error", response_summary=response_summary,
                )
                raise AIGenerationError("AI 生成失败：图片模型返回错误")
            can_retry = attempt + 1 < attempts
            logger.warning(
                "ark image %s (request_id=%s attempt=%d/%d)",
                empty_reason,
                request_id,
                attempt + 1,
                attempts,
            )
            log_event(
                "ark_image",
                status="retry" if can_retry else "failed",
                request_id=request_id,
                attempt=attempt + 1,
                attempts=attempts,
                latency_ms=latency_ms,
                reason=empty_reason,
                http_status=resp.status_code,
                response_summary=response_summary,
            )
            if can_retry:
                _sleep_before_retry(attempt, attempts)
                continue
            raise AIGenerationError("AI 生成失败：图片模型未返回图片")
        logger.info("ark image ok request_id=%s latency_ms=%d", request_id, latency_ms)
        log_event(
            "ark_image",
            status="success",
            request_id=request_id,
            attempt=attempt + 1,
            latency_ms=latency_ms,
        )
        return ImageGenerationResult(image_url=image_url, ext=_guess_ext(image_url))

    logger.error("ark image exhausted retries: %s", type(last_transient).__name__ if last_transient else "?")
    log_event(
        "ark_image",
        status="failed",
        reason="exhausted_retries",
        last_error=type(last_transient).__name__ if last_transient else None,
    )
    raise AIGenerationError("AI 生成失败：图片模型服务暂时不可用，请重试")


def _sleep_before_retry(attempt: int, attempts: int) -> None:
    if attempt + 1 >= attempts:
        return
    delay = max(0.0, settings.MODEL_RETRY_BACKOFF_SECONDS) * (attempt + 1)
    if delay:
        time.sleep(delay)


def _extract_image_url(payload: object) -> str | None:
    """Read the OpenAI-compatible `data[0].url` response."""
    if not isinstance(payload, dict):
        return None
    data = payload.get("data")
    if isinstance(data, list) and data:
        first = data[0]
        if isinstance(first, dict):
            url = first.get("url")
            if isinstance(url, str) and url.startswith(("https://", "http://")):
                return url
    return None


def _summarize_response(payload: object, response: httpx.Response) -> dict[str, object]:
    """Return a diagnostic response shape without image URLs or response bodies."""
    summary: dict[str, object] = {
        "payload_type": type(payload).__name__ if payload is not None else "invalid_json",
        "content_type": response.headers.get("content-type"),
        "body_bytes": len(response.content),
    }
    if not isinstance(payload, dict):
        return summary

    summary["top_level_keys"] = sorted(str(key) for key in payload)[:20]
    data = payload.get("data")
    summary["data_type"] = type(data).__name__
    if isinstance(data, list):
        summary["images_count"] = len(data)
    summary["error_codes"] = [str(error.get("code", ""))[:120] for error in _provider_errors(payload)]
    return summary


def _provider_errors(payload: object) -> list[dict]:
    if not isinstance(payload, dict):
        return []
    errors = []
    if isinstance(payload.get("error"), dict):
        errors.append(payload["error"])
    data = payload.get("data")
    if isinstance(data, list):
        errors.extend(
            item["error"] for item in data
            if isinstance(item, dict) and isinstance(item.get("error"), dict)
        )
    return errors


def _is_input_policy_violation(payload: object) -> bool:
    """Match only the provider's explicit input-policy rejection response."""
    return bool(_input_policy_codes(payload))


def _input_policy_codes(payload: object) -> list[str]:
    return [
        code
        for error in _provider_errors(payload)
        if (code := str(error.get("code", "")).split(".")[0]) in {
            "InputTextSensitiveContentDetected", "InputImageSensitiveContentDetected",
            "SensitiveContentDetected",
        }
    ]


def _guess_ext(url: str) -> str:
    lower = url.lower().split("?")[0]
    for ext in ("png", "jpeg", "jpg", "webp"):
        if lower.endswith(f".{ext}"):
            return "jpg" if ext == "jpeg" else ext
    return "jpg"
