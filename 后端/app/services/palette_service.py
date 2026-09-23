"""Extract a trip colour card from photo pixels and name it with traditional colours.

Each photo is median-cut quantised; colours are weighted by pixel share and
vividness (so sky-grey does not drown the one red temple wall), clustered by
their nearest traditional Chinese colour in CIELAB (ΔE76), and the swatch shown
is the weighted mean of the real photo colours inside that cluster.
"""

from __future__ import annotations

import math
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from PIL import Image

from app.models import dto
from app.services import storage_service

_TRADITIONAL_COLORS: tuple[tuple[str, str], ...] = (
    ("霜色", "E9F1F6"), ("月白", "D6E6EE"), ("缟色", "F2ECDE"), ("素白", "ECEBE4"),
    ("银白", "D8D9DC"), ("苍色", "75878A"), ("蓝灰", "A1AFC9"), ("烟灰", "8C8C88"),
    ("鸦青", "424C50"), ("墨色", "50616D"), ("玄青", "3D3B4F"), ("漆黑", "161823"),
    ("天青", "9FC4DA"), ("蔚蓝", "5E9CCB"), ("湖蓝", "3A8FB7"), ("靛青", "177CB0"),
    ("群青", "2E59A7"), ("藏青", "2E4E7E"), ("黛蓝", "425066"), ("花青", "3A5270"),
    ("天水碧", "5AA4AE"), ("青碧", "48C0A3"), ("石绿", "3F9F8C"), ("水色", "88ADA6"),
    ("黛绿", "426666"), ("松柏绿", "21A675"), ("竹青", "789262"), ("碧山", "779649"),
    ("苔绿", "6B7F3E"), ("松花绿", "BCE672"), ("艾绿", "A4CAB6"), ("豆绿", "9ED048"),
    ("墨绿", "2E4A3A"), ("缃色", "F0C239"), ("秋香", "D9B611"), ("鹅黄", "F4DE8A"),
    ("牙色", "EEDEB0"), ("杏黄", "F2A84A"), ("橘红", "E8743B"), ("琥珀", "CA6924"),
    ("赭石", "9C5333"), ("驼色", "A88462"), ("栗色", "6B3E2A"), ("檀色", "B36D61"),
    ("茶色", "8B6C4F"), ("土黄", "C8A060"), ("胭脂", "9D2933"), ("朱砂", "C63C26"),
    ("丹霞", "E36A4F"), ("海棠红", "DB5A6B"), ("桃红", "F09199"), ("藕荷", "D8B9C6"),
    ("雪青", "B0A4E3"), ("丁香", "CCA4E3"), ("黛紫", "574266"), ("绛紫", "8C4356"),
    ("青莲", "7E5A9B"),
)
_MIN_CLUSTER_DISTANCE = 10.0


@dataclass(frozen=True)
class TripPalette:
    colors: list[dto.PaletteColor]
    warmth: float
    chroma: float
    lightness: float


def extract_trip_palette(relative_paths: list[str], *, max_colors: int = 5) -> TripPalette:
    if not relative_paths:
        return TripPalette([], 0.5, 0.0, 0.5)
    workers = max(1, min(4, len(relative_paths)))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        per_photo = list(executor.map(_photo_colors, relative_paths))

    weights: dict[str, float] = {}
    lab_sums: dict[str, list[float]] = {}
    warm = chroma_sum = light_sum = total = 0.0
    for colors in per_photo:
        for share, lab in colors:
            name, _ = _nearest_name(lab)
            chroma = math.hypot(lab[1], lab[2])
            weight = share * _vividness(lab, chroma)
            weights[name] = weights.get(name, 0.0) + weight
            bucket = lab_sums.setdefault(name, [0.0, 0.0, 0.0])
            for index in range(3):
                bucket[index] += lab[index] * weight
            total += share
            chroma_sum += chroma * share
            light_sum += lab[0] * share
            if chroma > 8 and _is_warm_hue(lab):
                warm += share
    if not weights or total <= 0:
        return TripPalette([], 0.5, 0.0, 0.5)

    ranked = [
        (name, tuple(value / weight for value in lab_sums[name]), weight)
        for name, weight in sorted(weights.items(), key=lambda item: -item[1])
    ]
    chosen: list[tuple[str, tuple[float, float, float], float]] = []
    # A colour card reads as a place only when greys do not crowd it: keep at
    # most one neutral unless the photos offer nothing more colourful.
    for allow_neutrals in (1, max_colors):
        for name, mean, weight in ranked:
            if len(chosen) == max_colors:
                break
            if any(name == picked for picked, _, _ in chosen):
                continue
            if any(_delta_e(mean, other) < _MIN_CLUSTER_DISTANCE for _, other, _ in chosen):
                continue
            neutral_count = sum(_is_neutral(other) for _, other, _ in chosen)
            if _is_neutral(mean) and neutral_count >= allow_neutrals:
                continue
            chosen.append((name, mean, weight))
    chosen.sort(key=lambda item: -item[2])
    shares = _percentages([weight for _, _, weight in chosen])
    colors = [
        dto.PaletteColor(name=name, hex=_lab_to_hex(mean), share=share)
        for (name, mean, _), share in zip(chosen, shares, strict=True)
    ]
    return TripPalette(
        colors=colors,
        warmth=round(warm / total, 3),
        chroma=round(min(1.0, chroma_sum / total / 60.0), 3),
        lightness=round(light_sum / total / 100.0, 3),
    )


def _photo_colors(relative_path: str) -> list[tuple[float, tuple[float, float, float]]]:
    try:
        with Image.open(storage_service.resolve_static_path(relative_path)) as image:
            image.draft("RGB", (256, 256))
            small = image.convert("RGB")
            small.thumbnail((96, 96))
            quantized = small.quantize(colors=12, method=Image.Quantize.MEDIANCUT)
            palette = quantized.getpalette() or []
            counts = quantized.getcolors() or []
    except Exception:  # noqa: BLE001 - one unreadable photo must not drop the palette
        return []
    pixels = sum(count for count, _ in counts) or 1
    colors = []
    for count, index in counts:
        rgb = palette[index * 3:index * 3 + 3]
        if len(rgb) == 3:
            colors.append((count / pixels, _rgb_to_lab(tuple(rgb))))
    return colors


def _nearest_name(lab: tuple[float, float, float]) -> tuple[str, float]:
    return min(
        ((name, _delta_e(lab, reference)) for name, reference in _REFERENCE_LABS),
        key=lambda item: item[1],
    )


def _vividness(lab: tuple[float, float, float], chroma: float) -> float:
    weight = 0.2 + 0.8 * min(1.0, chroma / 35.0)
    if lab[0] < 20:
        weight *= 0.25
    elif lab[0] < 32:
        weight *= 0.6
    elif lab[0] > 94:
        weight *= 0.5
    return weight


def _is_neutral(lab: tuple[float, ...]) -> bool:
    return math.hypot(lab[1], lab[2]) < 9


def _is_warm_hue(lab: tuple[float, float, float]) -> bool:
    hue = math.degrees(math.atan2(lab[2], lab[1])) % 360
    return hue <= 100 or hue >= 330


def _delta_e(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b, strict=True)))


def _percentages(weights: list[float]) -> list[int]:
    total = sum(weights) or 1.0
    raw = [100 * weight / total for weight in weights]
    rounded = [int(value) for value in raw]
    for index in sorted(range(len(raw)), key=lambda i: -(raw[i] - rounded[i]))[: 100 - sum(rounded)]:
        rounded[index] += 1
    return rounded


def _rgb_to_lab(rgb: tuple[int, int, int]) -> tuple[float, float, float]:
    def linear(channel: int) -> float:
        value = channel / 255.0
        return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4

    r, g, b = (linear(channel) for channel in rgb)
    x = (0.4124 * r + 0.3576 * g + 0.1805 * b) / 0.95047
    y = 0.2126 * r + 0.7152 * g + 0.0722 * b
    z = (0.0193 * r + 0.1192 * g + 0.9505 * b) / 1.08883

    def f(t: float) -> float:
        return t ** (1 / 3) if t > 0.008856 else 7.787 * t + 16 / 116

    fx, fy, fz = f(x), f(y), f(z)
    return 116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)


def _lab_to_hex(lab: tuple[float, float, float]) -> str:
    lightness, a, b = lab
    fy = (lightness + 16) / 116
    fx, fz = fy + a / 500, fy - b / 200

    def inverse(t: float) -> float:
        return t ** 3 if t ** 3 > 0.008856 else (t - 16 / 116) / 7.787

    x, y, z = inverse(fx) * 0.95047, inverse(fy), inverse(fz) * 1.08883
    linear = (
        3.2406 * x - 1.5372 * y - 0.4986 * z,
        -0.9689 * x + 1.8758 * y + 0.0415 * z,
        0.0557 * x - 0.2040 * y + 1.0570 * z,
    )

    def gamma(value: float) -> int:
        value = max(0.0, min(1.0, value))
        value = 12.92 * value if value <= 0.0031308 else 1.055 * value ** (1 / 2.4) - 0.055
        return round(value * 255)

    return "#" + "".join(f"{gamma(channel):02X}" for channel in linear)


_REFERENCE_LABS: tuple[tuple[str, tuple[float, float, float]], ...] = tuple(
    (name, _rgb_to_lab((int(code[0:2], 16), int(code[2:4], 16), int(code[4:6], 16))))
    for name, code in _TRADITIONAL_COLORS
)
