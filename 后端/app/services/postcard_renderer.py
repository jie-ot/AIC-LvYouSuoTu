"""Local postcard finishing and truthful fallback rendering."""

from __future__ import annotations

import base64
import io
import os
from dataclasses import dataclass

from PIL import Image, ImageDraw, ImageFont, ImageOps

from app.core.config import settings
from app.core.exceptions import InternalError

CANVAS = (1500, 1000)
SAFE_MARGIN = 54
PROMPT_VERSION = "postcard-v3"


@dataclass(frozen=True)
class ComposedPostcard:
    content: bytes
    render_mode: str
    font_missing: bool


def decode_data_url(data_url: str) -> bytes:
    try:
        header, payload = data_url.split(",", 1)
        if not header.startswith("data:image/") or ";base64" not in header:
            raise ValueError
        return base64.b64decode(payload, validate=True)
    except Exception as exc:  # noqa: BLE001
        raise InternalError("明信片参考图解码失败") from exc


def compose_postcard(source: bytes, title: str, *, fallback: bool) -> ComposedPostcard:
    """Fit without cropping, then place title inside a measured safe area."""
    try:
        with Image.open(io.BytesIO(source)) as opened:
            opened.load()
            if opened.width * opened.height > settings.GENERATED_IMAGE_MAX_PIXELS:
                raise ValueError("too many pixels")
            image = ImageOps.exif_transpose(opened).convert("RGB")
    except Exception as exc:  # noqa: BLE001
        raise InternalError("明信片底图无法解码") from exc

    background = Image.new("RGB", CANVAS, (244, 241, 234))
    available = (CANVAS[0] - SAFE_MARGIN * 2, CANVAS[1] - SAFE_MARGIN * 2)
    fitted = ImageOps.contain(image, available, Image.Resampling.LANCZOS)
    x = (CANVAS[0] - fitted.width) // 2
    y = (CANVAS[1] - fitted.height) // 2
    background.paste(fitted, (x, y))
    draw = ImageDraw.Draw(background, "RGBA")
    draw.rounded_rectangle(
        (SAFE_MARGIN - 10, SAFE_MARGIN - 10, CANVAS[0] - SAFE_MARGIN + 10, CANVAS[1] - SAFE_MARGIN + 10),
        radius=18, outline=(255, 255, 255, 205), width=4,
    )

    safe_title = " ".join(title.strip().split())[:24]
    max_text_width = CANVAS[0] - (SAFE_MARGIN + 28) * 2 - 56
    font = None
    text_bbox = None
    for font_size in (54, 48, 42, 36, 32):
        candidate = _load_font(font_size)
        if candidate is None:
            break
        bbox = draw.textbbox((0, 0), safe_title, font=candidate)
        font = candidate
        text_bbox = bbox
        if bbox[2] - bbox[0] <= max_text_width:
            break
    render_mode = "local_fallback" if fallback else "ai_composite"
    if font is not None and text_bbox is not None and safe_title:
        text_width = min(text_bbox[2] - text_bbox[0], max_text_width)
        text_height = text_bbox[3] - text_bbox[1]
        panel_x = SAFE_MARGIN + 28
        panel_y = CANVAS[1] - SAFE_MARGIN - text_height - 58
        panel_right = panel_x + text_width + 56
        draw.rounded_rectangle(
            (panel_x, panel_y, panel_right, CANVAS[1] - SAFE_MARGIN - 18),
            radius=16, fill=(13, 31, 43, 178),
        )
        draw.text((panel_x + 28, panel_y + 18), safe_title, font=font, fill=(255, 255, 255, 245))
    else:
        render_mode = "local_no_text"

    output = io.BytesIO()
    background.save(output, format="JPEG", quality=91, optimize=True, progressive=True)
    content = output.getvalue()
    validate_postcard_bytes(content)
    return ComposedPostcard(content=content, render_mode=render_mode, font_missing=font is None)


def validate_postcard_bytes(content: bytes) -> tuple[int, int]:
    try:
        with Image.open(io.BytesIO(content)) as image:
            image.verify()
        with Image.open(io.BytesIO(content)) as image:
            image.load()
            width, height = image.size
            if width < 900 or height < 600:
                raise ValueError("dimensions too small")
            if width * height > settings.GENERATED_IMAGE_MAX_PIXELS:
                raise ValueError("too many pixels")
            ratio = width / height
            if not 1.35 <= ratio <= 1.75:
                raise ValueError("unsafe aspect ratio")
            return width, height
    except Exception as exc:  # noqa: BLE001
        raise InternalError("明信片成图质量校验失败") from exc


def _load_font(size: int):  # noqa: ANN202
    candidates = [
        settings.POSTCARD_FONT_PATH,
        "C:/Windows/Fonts/NotoSansSC-VF.ttf",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/opentype/source-han-sans/SourceHanSansSC-Regular.otf",
    ]
    for path in candidates:
        if path and os.path.isfile(path):
            try:
                return ImageFont.truetype(path, size=size)
            except OSError:
                continue
    return None
