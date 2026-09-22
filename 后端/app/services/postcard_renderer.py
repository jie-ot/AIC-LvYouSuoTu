"""Photo-specific postcard finishing and truthful local fallback rendering."""

from __future__ import annotations

import base64
import colorsys
import io
import os
from dataclasses import dataclass

from PIL import (
    Image,
    ImageDraw,
    ImageEnhance,
    ImageFilter,
    ImageFont,
    ImageOps,
    ImageStat,
)

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
PROMPT_VERSION = "postcard-v5"


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


def compose_postcard(
    source: bytes,
    title: str,
    *,
    fallback: bool,
    canvas_format: str = "landscape_3_2",
    layout_style: str = "editorial_full_bleed",
    title_placement: str = "bottom_left",
    typography_family: str = "modern_sans",
    typography_composition: str = "quiet_corner",
    typography_treatment: str = "solid",
    typography_scale: str = "balanced",
    typography_color_role: str = "auto_contrast",
    typography_rotation: int = 0,
    extra_texts: list[str] | None = None,
    emblem_style: str = "none",
    emblem_text: str = "",
    text_rendering: str = "local_exact",
) -> ComposedPostcard:
    """Apply the selected canvas and executable typography plan."""
    canvas_size = CANVAS_BY_FORMAT.get(canvas_format, CANVAS)
    image = _decode_image(source)
    background = (
        _compose_local_fallback(
            image,
            canvas_size=canvas_size,
            layout_style=layout_style,
            title_placement=title_placement,
        )
        if fallback
        else ImageOps.fit(
            image,
            canvas_size,
            method=Image.Resampling.LANCZOS,
            centering=_crop_center_for(title_placement),
        )
    )
    _draw_layout_finish(background, layout_style, image)

    font_missing = False
    local_copy = text_rendering == "local_exact"
    if local_copy and title.strip():
        title_font = _load_font(48, family=typography_family, bold=True)
        if title_font is None:
            font_missing = True
        else:
            _draw_typography(
                background,
                title=" ".join(title.strip().split())[:24],
                extra_texts=[
                    " ".join(text.strip().split())[:30]
                    for text in (extra_texts or [])[:2]
                    if text.strip()
                ],
                family=typography_family,
                composition=typography_composition,
                treatment=typography_treatment,
                scale=typography_scale,
                color_role=typography_color_role,
                rotation=max(-12, min(12, typography_rotation)),
                placement=title_placement,
                emblem_style=emblem_style,
                emblem_text=" ".join(emblem_text.strip().split())[:8],
            )

    prefix = "local" if fallback else "ai"
    suffix = "no_text_v5" if font_missing else "v5"
    render_mode = f"{prefix}_art_direction_{suffix}"
    output = io.BytesIO()
    background.convert("RGB").save(
        output,
        format="JPEG",
        quality=95,
        optimize=True,
        progressive=True,
    )
    content = output.getvalue()
    validate_postcard_bytes(content, expected_size=canvas_size)
    return ComposedPostcard(
        content=content,
        render_mode=render_mode,
        font_missing=font_missing,
    )


def _decode_image(source: bytes) -> Image.Image:
    try:
        with Image.open(io.BytesIO(source)) as opened:
            opened.load()
            if opened.width * opened.height > settings.GENERATED_IMAGE_MAX_PIXELS:
                raise ValueError("too many pixels")
            return ImageOps.exif_transpose(opened).convert("RGB")
    except Exception as exc:  # noqa: BLE001
        raise InternalError("明信片底图无法解码") from exc


def _compose_local_fallback(
    image: Image.Image,
    *,
    canvas_size: tuple[int, int],
    layout_style: str,
    title_placement: str,
) -> Image.Image:
    """Use the planned spatial mechanism if the cloud render is unavailable."""
    if layout_style == "editorial_full_bleed":
        return ImageOps.fit(
            image,
            canvas_size,
            method=Image.Resampling.LANCZOS,
            centering=_crop_center_for(title_placement),
        )
    if layout_style == "contact_sheet":
        return _contact_sheet(image, canvas_size)
    if layout_style == "color_field":
        return _color_field(image, canvas_size, title_placement)

    backdrop = ImageOps.fit(
        image,
        canvas_size,
        method=Image.Resampling.LANCZOS,
        centering=_crop_center_for(title_placement),
    )
    backdrop = ImageEnhance.Color(backdrop).enhance(0.68)
    backdrop = ImageEnhance.Brightness(backdrop).enhance(0.66)
    backdrop = backdrop.filter(
        ImageFilter.GaussianBlur(max(14, min(canvas_size) // 48))
    )
    canvas = backdrop.convert("RGBA")
    if layout_style == "split_echo":
        _paste_split_echo(canvas, image, title_placement)
    elif layout_style == "contour_cutout":
        _paste_contour_window(canvas, image, title_placement)
    else:
        _paste_paper_window(canvas, image, title_placement)
        if layout_style in {"tactile_collage", "map_grid"}:
            _draw_tactile_marks(canvas, image, title_placement)
    return canvas.convert("RGB")


def _contact_sheet(image: Image.Image, canvas_size: tuple[int, int]) -> Image.Image:
    width, height = canvas_size
    palette = _source_palette(image)
    canvas = Image.new("RGB", canvas_size, palette[2])
    gap = max(18, min(width, height) // 48)
    frame_count = 3 if width >= height else 4
    if width >= height:
        cell_w = (width - gap * (frame_count + 1)) // frame_count
        cell_h = height - gap * 2
        boxes = [(gap + index * (cell_w + gap), gap, cell_w, cell_h) for index in range(frame_count)]
    else:
        cell_w = width - gap * 2
        cell_h = (height - gap * (frame_count + 1)) // frame_count
        boxes = [(gap, gap + index * (cell_h + gap), cell_w, cell_h) for index in range(frame_count)]
    anchors = ((0.34, 0.5), (0.5, 0.5), (0.66, 0.5), (0.5, 0.64))
    for box, anchor in zip(boxes, anchors, strict=False):
        x, y, cell_w, cell_h = box
        frame = ImageOps.fit(
            image,
            (cell_w, cell_h),
            method=Image.Resampling.LANCZOS,
            centering=anchor,
        )
        canvas.paste(frame, (x, y))
    return canvas


def _color_field(
    image: Image.Image,
    canvas_size: tuple[int, int],
    title_placement: str,
) -> Image.Image:
    width, height = canvas_size
    dark, accent, light = _source_palette(image)
    canvas = Image.new("RGB", canvas_size, light)
    photo_w = int(width * (0.68 if width >= height else 0.88))
    photo_h = int(height * (0.88 if width >= height else 0.66))
    photo = ImageOps.fit(
        image,
        (photo_w, photo_h),
        method=Image.Resampling.LANCZOS,
        centering=_crop_center_for(title_placement),
    )
    x = width - photo_w if title_placement.endswith("left") else 0
    y = (height - photo_h) // 2
    canvas.paste(photo, (x, y))
    draw = ImageDraw.Draw(canvas, "RGBA")
    radius = max(70, min(width, height) // 8)
    cx = width - radius // 2 if x == 0 else radius // 2
    draw.ellipse(
        (cx - radius, height // 8, cx + radius, height // 8 + radius * 2),
        fill=(*accent, 190),
    )
    draw.line((cx, 0, cx, height), fill=(*dark, 88), width=max(2, width // 500))
    return canvas


def _paste_paper_window(
    canvas: Image.Image,
    image: Image.Image,
    title_placement: str,
) -> None:
    width, height = canvas.size
    typography_on_left = title_placement.endswith("left")
    max_box = (
        (int(width * 0.68), int(height * 0.82))
        if width >= height
        else (int(width * 0.84), int(height * 0.65))
    )
    fitted = ImageOps.contain(image, max_box, Image.Resampling.LANCZOS)
    border = max(12, min(width, height) // 60)
    card = Image.new(
        "RGBA",
        (fitted.width + border * 2, fitted.height + border * 2),
        (246, 241, 230, 255),
    )
    card.paste(fitted.convert("RGBA"), (border, border))
    angle = 1.5 if typography_on_left else -1.5
    card = card.rotate(angle, expand=True, resample=Image.Resampling.BICUBIC)
    x = width - card.width - int(width * 0.045) if typography_on_left else int(width * 0.045)
    y = (height - card.height) // 2
    shadow = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    shadow_card = Image.new("RGBA", card.size, (0, 0, 0, 82))
    shadow.alpha_composite(
        shadow_card.filter(ImageFilter.GaussianBlur(max(12, min(width, height) // 60))),
        (x + 14, y + 18),
    )
    canvas.alpha_composite(shadow)
    canvas.alpha_composite(card, (x, y))


def _paste_split_echo(
    canvas: Image.Image,
    image: Image.Image,
    title_placement: str,
) -> None:
    width, height = canvas.size
    horizontal = width >= height
    if horizontal:
        main_size = (int(width * 0.69), int(height * 0.82))
        main_x = int(width * 0.26) if title_placement.endswith("left") else int(width * 0.05)
        main_y = int(height * 0.09)
        strip_size = (int(width * 0.18), main_size[1])
        strip_x = int(width * 0.045) if main_x > width * 0.1 else width - strip_size[0] - int(width * 0.045)
        strip_y = main_y
    else:
        main_size = (int(width * 0.84), int(height * 0.62))
        main_x = int(width * 0.08)
        main_y = int(height * 0.26) if title_placement.startswith("top") else int(height * 0.08)
        strip_size = (main_size[0], int(height * 0.15))
        strip_x = main_x
        strip_y = int(height * 0.05) if main_y > height * 0.1 else height - strip_size[1] - int(height * 0.05)
    main = ImageOps.fit(image, main_size, method=Image.Resampling.LANCZOS)
    canvas.alpha_composite(main.convert("RGBA"), (main_x, main_y))
    strip_source = ImageOps.fit(image, strip_size, method=Image.Resampling.LANCZOS)
    for offset, alpha in ((0, 235), (max(10, min(width, height) // 60), 105)):
        strip = strip_source.convert("RGBA")
        strip.putalpha(alpha)
        canvas.alpha_composite(strip, (strip_x + offset, strip_y + offset // 2))


def _paste_contour_window(
    canvas: Image.Image,
    image: Image.Image,
    title_placement: str,
) -> None:
    width, height = canvas.size
    fitted = ImageOps.fit(
        image,
        (int(width * 0.88), int(height * 0.82)),
        method=Image.Resampling.LANCZOS,
        centering=_crop_center_for(title_placement),
    ).convert("RGBA")
    mask = Image.new("L", fitted.size, 0)
    draw = ImageDraw.Draw(mask)
    inset = max(8, min(width, height) // 80)
    draw.rounded_rectangle(
        (inset, inset, fitted.width - inset, fitted.height - inset),
        radius=min(fitted.size) // 5,
        fill=255,
    )
    mask = mask.filter(ImageFilter.GaussianBlur(max(2, inset // 3)))
    fitted.putalpha(mask)
    x = width - fitted.width if title_placement.endswith("left") else 0
    y = (height - fitted.height) // 2
    canvas.alpha_composite(fitted, (x, y))


def _draw_tactile_marks(
    canvas: Image.Image,
    image: Image.Image,
    title_placement: str,
) -> None:
    width, height = canvas.size
    dark, accent, light = _source_palette(image)
    marks = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(marks, "RGBA")
    side_x = width - int(width * 0.18) if title_placement.endswith("left") else int(width * 0.025)
    diameter = int(min(width, height) * 0.19)
    draw.ellipse(
        (side_x, int(height * 0.07), side_x + diameter, int(height * 0.07) + diameter),
        fill=(*accent, 105),
    )
    draw.arc(
        (
            side_x - diameter // 3,
            int(height * 0.61),
            side_x + diameter,
            int(height * 0.93),
        ),
        190,
        345,
        fill=(*light, 190),
        width=max(8, min(width, height) // 70),
    )
    for index in range(8):
        y = int(height * (0.14 + index * 0.075))
        draw.line(
            (side_x, y, side_x + diameter // 2, y - diameter // 12),
            fill=(*dark, 58),
            width=max(2, min(width, height) // 350),
        )
    canvas.alpha_composite(marks)


def _draw_layout_finish(
    image: Image.Image,
    layout_style: str,
    source: Image.Image,
) -> None:
    width, height = image.size
    dark, accent, light = _source_palette(source)
    draw = ImageDraw.Draw(image, "RGBA")
    unit = max(2, min(width, height) // 400)
    margin = min(width, height) // 28
    if layout_style in {"paper_portal", "contour_cutout"}:
        length = min(width, height) // 10
        for x, y, sx, sy in (
            (margin, margin, 1, 1),
            (width - margin, height - margin, -1, -1),
        ):
            draw.line((x, y, x + sx * length, y), fill=(*light, 190), width=unit)
            draw.line((x, y, x, y + sy * length), fill=(*light, 190), width=unit)
    elif layout_style == "map_grid":
        for index in range(1, 6):
            x = int(width * index / 6)
            draw.line((x, 0, x, height), fill=(*light, 32), width=unit)
        for index in range(1, 6):
            y = int(height * index / 6)
            draw.line((0, y, width, y), fill=(*light, 32), width=unit)
        draw.arc(
            (margin, margin, width - margin, height - margin),
            205,
            334,
            fill=(*accent, 142),
            width=unit * 2,
        )
    elif layout_style == "tactile_collage":
        draw.line(
            (margin, height - margin, width // 3, height - margin),
            fill=(*accent, 210),
            width=unit * 3,
        )
    elif layout_style == "split_echo":
        draw.line(
            (width - margin, margin, width - margin, height // 3),
            fill=(*light, 180),
            width=unit,
        )
    elif layout_style == "contact_sheet":
        draw.rectangle(
            (margin // 2, margin // 2, width - margin // 2, height - margin // 2),
            outline=(*dark, 100),
            width=unit,
        )


def _draw_typography(
    image: Image.Image,
    *,
    title: str,
    extra_texts: list[str],
    family: str,
    composition: str,
    treatment: str,
    scale: str,
    color_role: str,
    rotation: int,
    placement: str,
    emblem_style: str,
    emblem_text: str,
) -> None:
    width, height = image.size
    region = _title_region(image.size, placement)
    dark, accent, light = _source_palette(image)
    ink, support = _typography_colors(
        image,
        region,
        role=color_role,
        dark=dark,
        accent=accent,
        light=light,
    )
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay, "RGBA")
    scale_factor = {
        "review_reduced": 0.045,
        "restrained": 0.062,
        "balanced": 0.085,
        "bold": 0.125,
        "hero": 0.19,
    }.get(scale, 0.085)
    base_size = max(34, int(min(width, height) * scale_factor))

    if composition == "vertical_spine":
        _draw_vertical_title(
            draw,
            image.size,
            title,
            family,
            base_size,
            placement,
            treatment,
            ink,
            support,
        )
    else:
        text = title
        if composition == "split_stack" and len(title) >= 4:
            split = (len(title) + 1) // 2
            text = title[:split] + "\n" + title[split:]
        max_width = {
            "quiet_corner": int(width * 0.48),
            "oversized_crop": int(width * 1.08),
            "split_stack": int(width * 0.62),
            "outline_echo": int(width * 0.78),
            "angled_label": int(width * 0.62),
            "center_stage": int(width * 0.82),
        }.get(composition, int(width * 0.5))
        if composition == "oversized_crop":
            base_size = max(base_size, int(min(width, height) * 0.24))
        font = _fit_font(
            text,
            family=family,
            start_size=base_size,
            max_width=max_width,
            max_height=int(height * 0.5),
            multiline="\n" in text,
        )
        if font is not None:
            bbox = _text_bbox(draw, text, font)
            text_size = (bbox[2] - bbox[0], bbox[3] - bbox[1])
            xy = _title_position(
                image.size,
                text_size,
                placement=placement,
                composition=composition,
            )
            if treatment == "paper_cutout" or composition == "angled_label":
                pad = max(14, min(width, height) // 55)
                draw.rounded_rectangle(
                    (
                        xy[0] - pad,
                        xy[1] - pad,
                        xy[0] + text_size[0] + pad,
                        xy[1] + text_size[1] + pad,
                    ),
                    radius=pad,
                    fill=(*light, 226),
                    outline=(*accent, 185),
                    width=max(2, pad // 6),
                )
                if _luminance(ink) > 190:
                    ink = dark
            _draw_treated_text(
                draw,
                xy,
                text,
                font=font,
                treatment=treatment,
                ink=ink,
                support=support,
                echo=composition == "outline_echo",
            )

    if rotation or composition == "angled_label":
        angle = rotation or (-5 if placement.endswith("left") else 5)
        overlay = overlay.rotate(
            angle,
            resample=Image.Resampling.BICUBIC,
            center=(width // 2, height // 2),
        )
    image.paste(overlay, (0, 0), overlay)
    _draw_supporting_copy(image, extra_texts, family, placement, ink, support)
    _draw_emblem(image, emblem_style, emblem_text, family, placement, ink, support)


def _draw_vertical_title(
    draw: ImageDraw.ImageDraw,
    canvas_size: tuple[int, int],
    title: str,
    family: str,
    base_size: int,
    placement: str,
    treatment: str,
    ink: tuple[int, int, int],
    support: tuple[int, int, int],
) -> None:
    width, height = canvas_size
    available_h = int(height * 0.78)
    font = _fit_vertical_font(title, family, base_size, available_h)
    if font is None:
        return
    sample = draw.textbbox((0, 0), "国", font=font, stroke_width=2)
    char_w = sample[2] - sample[0]
    step = max(char_w, int(font.size * 1.02))
    total_h = step * len(title)
    margin = max(22, min(width, height) // 24)
    x = margin if placement.endswith("left") else width - margin - char_w
    y = margin if placement.startswith("top") else height - margin - total_h
    for index, char in enumerate(title):
        _draw_treated_text(
            draw,
            (x, y + index * step),
            char,
            font=font,
            treatment=treatment,
            ink=ink,
            support=support,
            echo=False,
        )


def _draw_treated_text(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    text: str,
    *,
    font: ImageFont.FreeTypeFont,
    treatment: str,
    ink: tuple[int, int, int],
    support: tuple[int, int, int],
    echo: bool,
) -> None:
    stroke = max(2, font.size // 30)
    offset = max(4, font.size // 12)
    if echo:
        for multiplier, alpha in ((3, 48), (2, 82), (1, 125)):
            draw.multiline_text(
                (xy[0] + offset * multiplier, xy[1] + offset * multiplier),
                text,
                font=font,
                fill=(*support, alpha),
                spacing=max(2, font.size // 10),
                stroke_width=stroke,
                stroke_fill=(*support, alpha),
            )
    if treatment == "outline":
        draw.multiline_text(
            xy,
            text,
            font=font,
            fill=(*ink, 36),
            spacing=max(2, font.size // 10),
            stroke_width=stroke * 2,
            stroke_fill=(*ink, 246),
        )
    elif treatment == "offset_shadow":
        draw.multiline_text(
            (xy[0] + offset, xy[1] + offset),
            text,
            font=font,
            fill=(*support, 210),
            spacing=max(2, font.size // 10),
        )
        draw.multiline_text(xy, text, font=font, fill=(*ink, 250), spacing=max(2, font.size // 10))
    elif treatment == "duotone":
        draw.multiline_text(
            (xy[0] - offset, xy[1] + offset // 2),
            text,
            font=font,
            fill=(*support, 232),
            spacing=max(2, font.size // 10),
        )
        draw.multiline_text(xy, text, font=font, fill=(*ink, 246), spacing=max(2, font.size // 10))
    elif treatment == "translucent":
        draw.multiline_text(xy, text, font=font, fill=(*ink, 166), spacing=max(2, font.size // 10))
    else:
        draw.multiline_text(
            xy,
            text,
            font=font,
            fill=(*ink, 248),
            spacing=max(2, font.size // 10),
            stroke_width=stroke if treatment == "paper_cutout" else 0,
            stroke_fill=(*support, 165),
        )


def _draw_supporting_copy(
    image: Image.Image,
    extra_texts: list[str],
    family: str,
    placement: str,
    ink: tuple[int, int, int],
    support: tuple[int, int, int],
) -> None:
    if not extra_texts:
        return
    width, height = image.size
    font = _load_font(max(18, min(width, height) // 43), family=family, bold=False)
    if font is None:
        return
    draw = ImageDraw.Draw(image, "RGBA")
    margin = max(24, min(width, height) // 24)
    left = placement.endswith("left")
    top = placement.startswith("top")
    anchor = "la" if left else "ra"
    x = margin if left else width - margin
    y = height - margin - font.size * (len(extra_texts) + 1) if top else margin
    line_end = x + (min(width, height) // 9 if left else -min(width, height) // 9)
    draw.line((x, y, line_end, y), fill=(*support, 205), width=max(2, font.size // 10))
    for index, text in enumerate(extra_texts):
        draw.text(
            (x, y + font.size * (index + 1.35)),
            text,
            font=font,
            fill=(*ink, 225),
            anchor=anchor,
        )


def _draw_emblem(
    image: Image.Image,
    style: str,
    text: str,
    family: str,
    placement: str,
    ink: tuple[int, int, int],
    support: tuple[int, int, int],
) -> None:
    if style == "none" or not text:
        return
    width, height = image.size
    diameter = max(72, min(width, height) // 11)
    margin = max(24, min(width, height) // 24)
    x0 = width - margin - diameter if placement.endswith("left") else margin
    y0 = height - margin - diameter if placement.startswith("top") else margin
    draw = ImageDraw.Draw(image, "RGBA")
    line_width = max(2, diameter // 28)
    box = (x0, y0, x0 + diameter, y0 + diameter)
    if style == "seal":
        draw.ellipse(box, fill=(*support, 42), outline=(*ink, 225), width=line_width)
        draw.ellipse(
            (x0 + line_width * 3, y0 + line_width * 3, x0 + diameter - line_width * 3, y0 + diameter - line_width * 3),
            outline=(*ink, 145),
            width=line_width,
        )
    elif style == "geometric_mark":
        draw.polygon(
            ((x0 + diameter // 2, y0), (x0 + diameter, y0 + diameter), (x0, y0 + diameter)),
            fill=(*support, 72),
            outline=(*ink, 225),
        )
    else:
        draw.rounded_rectangle(
            box,
            radius=diameter // 6,
            fill=(*support, 45),
            outline=(*ink, 225),
            width=line_width,
        )
    font = _fit_font(
        text,
        family=family,
        start_size=diameter // 3,
        max_width=int(diameter * 0.72),
        max_height=int(diameter * 0.5),
    )
    if font is not None:
        draw.text(
            (x0 + diameter // 2, y0 + diameter // 2),
            text,
            font=font,
            fill=(*ink, 238),
            anchor="mm",
        )


def _title_position(
    canvas_size: tuple[int, int],
    text_size: tuple[int, int],
    *,
    placement: str,
    composition: str,
) -> tuple[int, int]:
    width, height = canvas_size
    text_width, text_height = text_size
    margin = max(26, min(width, height) // 22)
    if composition == "center_stage":
        return ((width - text_width) // 2, (height - text_height) // 2)
    if composition == "oversized_crop":
        x = -int(text_width * 0.035) if placement.endswith("left") else width - text_width + int(text_width * 0.035)
        y = -int(text_height * 0.08) if placement.startswith("top") else height - text_height + int(text_height * 0.08)
        return (x, y)
    left = placement.endswith("left")
    top = placement.startswith("top")
    x = margin if left else width - margin - text_width
    y = margin if top else height - margin - text_height
    if composition == "outline_echo":
        x = (width - text_width) // 2
    return (x, y)


def _fit_font(
    text: str,
    *,
    family: str,
    start_size: int,
    max_width: int,
    max_height: int,
    multiline: bool = False,
) -> ImageFont.FreeTypeFont | None:
    for size in range(max(20, start_size), 19, -4):
        font = _load_font(size, family=family, bold=True)
        if font is None:
            return None
        probe = ImageDraw.Draw(Image.new("RGB", (8, 8)))
        bbox = (
            probe.multiline_textbbox((0, 0), text, font=font, spacing=max(2, size // 10))
            if multiline
            else probe.textbbox((0, 0), text, font=font)
        )
        if bbox[2] - bbox[0] <= max_width and bbox[3] - bbox[1] <= max_height:
            return font
    return _load_font(20, family=family, bold=True)


def _fit_vertical_font(
    text: str,
    family: str,
    start_size: int,
    max_height: int,
) -> ImageFont.FreeTypeFont | None:
    for size in range(max(20, start_size), 19, -4):
        if size * len(text) <= max_height:
            return _load_font(size, family=family, bold=True)
    return _load_font(20, family=family, bold=True)


def _text_bbox(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont,
) -> tuple[int, int, int, int]:
    if "\n" in text:
        return draw.multiline_textbbox((0, 0), text, font=font, spacing=max(2, font.size // 10))
    return draw.textbbox((0, 0), text, font=font)


def _typography_colors(
    image: Image.Image,
    region: tuple[int, int, int, int],
    *,
    role: str,
    dark: tuple[int, int, int],
    accent: tuple[int, int, int],
    light: tuple[int, int, int],
) -> tuple[tuple[int, int, int], tuple[int, int, int]]:
    if role == "source_dark":
        return dark, light
    if role == "source_light":
        return light, dark
    if role == "source_accent":
        return accent, light if _luminance(accent) < 150 else dark
    if role == "complementary":
        complement = tuple(255 - channel for channel in accent)
        return complement, accent
    local_luminance = _region_luminance(image, region)
    return (light, accent) if local_luminance < 145 else (dark, accent)


def _source_palette(
    image: Image.Image,
) -> tuple[tuple[int, int, int], tuple[int, int, int], tuple[int, int, int]]:
    sample = image.convert("RGB").resize((72, 72), Image.Resampling.BILINEAR)
    quantized = sample.quantize(colors=8, method=Image.Quantize.MEDIANCUT).convert("RGB")
    colors = sorted(quantized.getcolors(72 * 72) or [], reverse=True)
    values = [color for _, color in colors] or [(35, 47, 54), (196, 96, 64), (239, 234, 221)]
    dark = min(values, key=_luminance)
    light = max(values, key=_luminance)

    def saturation(color: tuple[int, int, int]) -> float:
        return colorsys.rgb_to_hsv(*(channel / 255 for channel in color))[1]

    accent = max(values, key=lambda color: saturation(color) * 1.35 + abs(_luminance(color) - 128) / 255)
    if _luminance(light) < 185:
        light = tuple(min(255, int(channel * 0.55 + 125)) for channel in light)
    if _luminance(dark) > 80:
        dark = tuple(max(0, int(channel * 0.55)) for channel in dark)
    return dark, accent, light


def _crop_center_for(title_placement: str) -> tuple[float, float]:
    x = 0.58 if title_placement.endswith("left") else 0.42
    y = 0.56 if title_placement.startswith("top") else 0.44
    return x, y


def _title_region(
    canvas_size: tuple[int, int], placement: str
) -> tuple[int, int, int, int]:
    width, height = canvas_size
    region_w = int(width * 0.56)
    region_h = int(height * 0.38)
    x0 = 0 if placement.endswith("left") else width - region_w
    y0 = 0 if placement.startswith("top") else height - region_h
    return (x0, y0, x0 + region_w, y0 + region_h)


def _region_luminance(image: Image.Image, region: tuple[int, int, int, int]) -> float:
    sample = image.crop(region).resize((32, 16), Image.Resampling.BILINEAR).convert("L")
    return float(ImageStat.Stat(sample).mean[0])


def _luminance(color: tuple[int, int, int]) -> float:
    return 0.2126 * color[0] + 0.7152 * color[1] + 0.0722 * color[2]


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


def _load_font(
    size: int,
    *,
    family: str = "modern_sans",
    bold: bool = False,
):  # noqa: ANN202
    windows = {
        "modern_sans": ("msyhbd.ttc", "msyh.ttc", "simhei.ttf"),
        "condensed_sans": ("simhei.ttf", "msyhbd.ttc", "msyh.ttc"),
        "editorial_serif": ("STSONG.TTF", "simsun.ttc", "simfang.ttf"),
        "rounded_display": ("msyhbd.ttc", "msyh.ttc", "simhei.ttf"),
        "handwritten": ("STXINGKA.TTF", "STKAITI.TTF", "simkai.ttf"),
        "stencil": ("simhei.ttf", "msyhbd.ttc", "msyh.ttc"),
        "monospace": ("msyh.ttc", "simfang.ttf", "simsun.ttc"),
    }
    names = windows.get(family, windows["modern_sans"])
    candidates = [settings.POSTCARD_FONT_PATH]
    candidates.extend(f"C:/Windows/Fonts/{name}" for name in names)
    if bold:
        candidates.extend(
            [
                "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
                "/usr/share/fonts/opentype/source-han-sans/SourceHanSansSC-Bold.otf",
            ]
        )
    candidates.extend(
        [
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/opentype/source-han-sans/SourceHanSansSC-Regular.otf",
        ]
    )
    for path in candidates:
        if path and os.path.isfile(path):
            try:
                return ImageFont.truetype(path, size=size)
            except OSError:
                continue
    return None
