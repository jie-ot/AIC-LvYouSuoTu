"""Preserve model-generated postcard artwork without drawing local text."""

from __future__ import annotations

import base64
import io
from dataclasses import dataclass

from PIL import Image, ImageOps

from app.core.config import settings
from app.core.exceptions import InternalError

CANVAS_BY_FORMAT = {
    "landscape_3_2": (1500, 1000),
    "landscape_4_3": (1440, 1080),
    "landscape_16_9": (1600, 900),
    "square_1_1": (1200, 1200),
    "portrait_4_5": (1080, 1350),
    "portrait_2_3": (1000, 1500),
}
CANVAS = CANVAS_BY_FORMAT["landscape_3_2"]
PROMPT_VERSION = "postcard-v6"


@dataclass(frozen=True)
class ComposedPostcard:
    content: bytes
    render_mode: str


def decode_data_url(data_url: str) -> bytes:
    try:
        header, payload = data_url.split(",", 1)
        if not header.startswith("data:image/") or ";base64" not in header:
            raise ValueError
        return base64.b64decode(payload, validate=True)
    except Exception as exc:  # noqa: BLE001
        raise InternalError("明信片参考图解码失败") from exc


def compose_postcard(
    source: bytes,
    *,
    fallback: bool,
    canvas_format: str = "landscape_3_2",
) -> ComposedPostcard:
    """Encode the artwork at its planned size without cropping model text."""
    canvas_size = CANVAS_BY_FORMAT.get(canvas_format, CANVAS)
    try:
        with Image.open(io.BytesIO(source)) as opened:
            opened.load()
            if opened.width * opened.height > settings.GENERATED_IMAGE_MAX_PIXELS:
                raise ValueError("too many pixels")
            image = ImageOps.exif_transpose(opened).convert("RGB")
    except Exception as exc:  # noqa: BLE001
        raise InternalError("明信片底图无法解码") from exc

    if image.size != canvas_size:
        # The provider may return a nearby ratio. Contain keeps every glyph in
        # frame; cropping a model-rendered title would corrupt the deliverable.
        fitted = ImageOps.contain(image, canvas_size, Image.Resampling.LANCZOS)
        canvas = Image.new("RGB", canvas_size, image.getpixel((0, 0)))
        canvas.paste(
            fitted,
            ((canvas_size[0] - fitted.width) // 2, (canvas_size[1] - fitted.height) // 2),
        )
        image = canvas

    output = io.BytesIO()
    image.save(output, format="JPEG", quality=95, optimize=True, progressive=True)
    content = output.getvalue()
    validate_postcard_bytes(content, expected_size=canvas_size)
    return ComposedPostcard(
        content=content,
        render_mode="source_photo_fallback_v6" if fallback else "ai_model_integrated_v6",
    )


def validate_postcard_bytes(
    content: bytes,
    *,
    expected_size: tuple[int, int] | None = None,
) -> tuple[int, int]:
    try:
        with Image.open(io.BytesIO(content)) as image:
            image.verify()
        with Image.open(io.BytesIO(content)) as image:
            image.load()
            width, height = image.size
            if min(width, height) < 800:
                raise ValueError("dimensions too small")
            if width * height > settings.GENERATED_IMAGE_MAX_PIXELS:
                raise ValueError("too many pixels")
            ratio = width / height
            if not 0.62 <= ratio <= 1.82:
                raise ValueError("unsafe aspect ratio")
            if expected_size is not None and (width, height) != expected_size:
                raise ValueError("unexpected planned canvas")
            return width, height
    except Exception as exc:  # noqa: BLE001
        raise InternalError("明信片成图质量校验失败") from exc
