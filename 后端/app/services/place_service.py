"""Resolve photo GPS metadata into readable places and one trip route.

Pipeline: EXIF WGS-84 coordinates → GCJ-02 (AMap datum) → batched reverse
geocoding → per-photo ``city / spot`` labels → hierarchical vote for the trip
destination (city when one stop dominates, otherwise province) and an ordered
route of distinct stops.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.ai.tools import amap_provider

_COORD_TEXT = re.compile(
    r"纬度\s*(-?\d+(?:\.\d+)?)\s*[，,]\s*经度\s*(-?\d+(?:\.\d+)?)"
)
_MUNICIPALITIES = ("北京", "上海", "天津", "重庆", "香港", "澳门")
# "风景名胜;风景名胜相关" covers ticket booths, gates and shops inside scenic
# areas; only headline attractions and museums are named on the report.
_SCENIC_POI_PREFIXES = (
    "风景名胜;风景名胜;", "风景名胜;公园广场", "科教文化服务;博物馆", "科教文化服务;美术馆",
)
_SPOT_SUFFIX = re.compile(
    r"(?:国家级)?(?:旅游)?(?:风景名胜区|风景区|景区|旅游区|度假区|国家公园|生态廊道|景点)$"
)
_DOMINANT_STOP_SHARE = 0.8


@dataclass(frozen=True)
class GeoPoint:
    latitude: float
    longitude: float
    altitude: float | None = None


@dataclass(frozen=True)
class PhotoPlace:
    asset_id: str
    point: GeoPoint
    province: str | None = None
    city: str | None = None
    spot: str | None = None

    @property
    def label(self) -> str | None:
        parts = [part for part in (self.city, self.spot) if part]
        if len(parts) == 2 and parts[1].startswith(parts[0]):
            parts = parts[1:]
        return "·".join(parts) or None


@dataclass
class TripPlaces:
    by_asset: dict[str, PhotoPlace] = field(default_factory=dict)
    destination: str | None = None
    route: list[str] = field(default_factory=list)
    spots: list[str] = field(default_factory=list)
    provinces: list[str] = field(default_factory=list)

    @property
    def resolved(self) -> bool:
        return bool(self.destination)


def photo_point(photo: Any) -> GeoPoint | None:
    """Read structured coordinates, falling back to the legacy text form."""
    lat = getattr(photo, "latitude", None)
    lng = getattr(photo, "longitude", None)
    if lat is None or lng is None:
        match = _COORD_TEXT.search(str(getattr(photo, "location", "") or ""))
        if not match:
            return None
        lat, lng = float(match.group(1)), float(match.group(2))
    try:
        lat, lng = float(lat), float(lng)
    except (TypeError, ValueError):
        return None
    if not (-90 <= lat <= 90 and -180 <= lng <= 180) or (lat == 0 and lng == 0):
        return None
    altitude = getattr(photo, "altitude", None)
    try:
        altitude = float(altitude) if altitude is not None else None
    except (TypeError, ValueError):
        altitude = None
    # Phones write 0 when the altitude is unknown.
    if altitude is not None and not 1 <= altitude <= 9000:
        altitude = None
    return GeoPoint(lat, lng, altitude)


def photo_time(photo: Any) -> datetime | None:
    value = str(getattr(photo, "taken_at", "") or "").strip()
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=None)


def haversine_km(a: GeoPoint, b: GeoPoint) -> float:
    lat1, lng1, lat2, lng2 = map(math.radians, (a.latitude, a.longitude, b.latitude, b.longitude))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lng2 - lng1) / 2) ** 2
    return 6371.0088 * 2 * math.asin(math.sqrt(h))


def wgs84_to_gcj02(lat: float, lng: float) -> tuple[float, float]:
    """Shift a GPS coordinate onto the datum used by AMap inside mainland China."""
    if not (73.66 < lng < 135.05 and 3.86 < lat < 53.55):
        return lat, lng
    a = 6378245.0
    ee = 0.00669342162296594323
    x, y = lng - 105.0, lat - 35.0
    dlat = (
        -100.0 + 2.0 * x + 3.0 * y + 0.2 * y * y + 0.1 * x * y + 0.2 * math.sqrt(abs(x))
        + (20.0 * math.sin(6.0 * x * math.pi) + 20.0 * math.sin(2.0 * x * math.pi)) * 2.0 / 3.0
        + (20.0 * math.sin(y * math.pi) + 40.0 * math.sin(y / 3.0 * math.pi)) * 2.0 / 3.0
        + (160.0 * math.sin(y / 12.0 * math.pi) + 320 * math.sin(y * math.pi / 30.0)) * 2.0 / 3.0
    )
    dlng = (
        300.0 + x + 2.0 * y + 0.1 * x * x + 0.1 * x * y + 0.1 * math.sqrt(abs(x))
        + (20.0 * math.sin(6.0 * x * math.pi) + 20.0 * math.sin(2.0 * x * math.pi)) * 2.0 / 3.0
        + (20.0 * math.sin(x * math.pi) + 40.0 * math.sin(x / 3.0 * math.pi)) * 2.0 / 3.0
        + (150.0 * math.sin(x / 12.0 * math.pi) + 300.0 * math.sin(x / 30.0 * math.pi)) * 2.0 / 3.0
    )
    radlat = lat / 180.0 * math.pi
    magic = 1 - ee * math.sin(radlat) ** 2
    sqrt_magic = math.sqrt(magic)
    dlat = (dlat * 180.0) / ((a * (1 - ee)) / (magic * sqrt_magic) * math.pi)
    dlng = (dlng * 180.0) / (a / sqrt_magic * math.cos(radlat) * math.pi)
    return lat + dlat, lng + dlng


def short_region(name: str | None) -> str | None:
    """云南省 → 云南, 迪庆藏族自治州 → 迪庆, 石林彝族自治县 → 石林."""
    value = _text(name)
    if not value:
        return None
    value = re.sub(r"(?:特别行政区|维吾尔自治区|壮族自治区|回族自治区|自治区|省)$", "", value)
    value = re.sub(r"(?:[\u4e00-\u9fff]{1,6}?族)+自治(?:州|县|旗)$", "", value)
    trimmed = re.sub(r"(?:市|地区|盟|林区|新区|县|区)$", "", value)
    return trimmed if len(trimmed) >= 2 else value


def resolve_trip_places(photos: list[Any]) -> TripPlaces:
    """Reverse-geocode every geotagged photo and vote a destination + route."""
    points: dict[str, GeoPoint] = {}
    for photo in photos:
        point = photo_point(photo)
        if point is not None:
            points[str(photo.asset_id)] = point
    places = TripPlaces()
    if not points:
        return places

    # ~100 m buckets keep batches small without merging distinct stops.
    bucket_of = {
        asset_id: (round(point.latitude, 3), round(point.longitude, 3))
        for asset_id, point in points.items()
    }
    buckets = list(dict.fromkeys(bucket_of.values()))
    queries = []
    for lat, lng in buckets:
        glat, glng = wgs84_to_gcj02(lat, lng)
        queries.append(f"{glng:.6f},{glat:.6f}")
    entries = dict(zip(buckets, amap_provider.reverse_geocode_batch(queries), strict=True))

    for asset_id, point in points.items():
        entry = entries.get(bucket_of[asset_id])
        province, city, spot = _parse_regeo(entry)
        places.by_asset[asset_id] = PhotoPlace(
            asset_id=asset_id, point=point, province=province, city=city, spot=spot,
        )

    ordered = sorted(
        (place for place in places.by_asset.values() if place.city),
        key=lambda place: (_time_key(photos, place.asset_id), place.asset_id),
    )
    places.route = list(dict.fromkeys(place.city for place in ordered if place.city))
    places.spots = list(dict.fromkeys(place.spot for place in ordered if place.spot))[:8]
    province_counts = Counter(place.province for place in ordered if place.province)
    places.provinces = [name for name, _ in province_counts.most_common()]
    city_counts = Counter(place.city for place in ordered if place.city)
    if city_counts:
        top_city, top_count = city_counts.most_common(1)[0]
        if len(city_counts) == 1 or top_count / sum(city_counts.values()) >= _DOMINANT_STOP_SHARE:
            places.destination = top_city
        elif len(places.provinces) == 1:
            places.destination = places.provinces[0]
        else:
            places.destination = " · ".join(places.provinces[:2])
    return places


def _parse_regeo(entry: dict | None) -> tuple[str | None, str | None, str | None]:
    if not isinstance(entry, dict):
        return None, None, None
    component = entry.get("addressComponent") if isinstance(entry.get("addressComponent"), dict) else {}
    province_raw = _text(component.get("province"))
    city_raw = _text(component.get("city"))
    district_raw = _text(component.get("district"))
    province = short_region(province_raw)
    if province in _MUNICIPALITIES or not city_raw:
        city = province if province in _MUNICIPALITIES else short_region(district_raw) or province
    elif re.search(r"(?:自治州|地区|盟)$", city_raw) and district_raw.endswith("市"):
        city = short_region(district_raw)
    else:
        city = short_region(city_raw)
    return province, city, _spot_name(entry, city)


def _spot_name(entry: dict, city: str | None) -> str | None:
    candidates: list[tuple[int, float, str]] = []
    for aoi in entry.get("aois") or []:
        if not isinstance(aoi, dict):
            continue
        kind = str(aoi.get("type") or "")
        distance = _float(aoi.get("distance"))
        if kind.startswith("11") and distance <= 300:
            # 110202 marks nationally listed scenic areas: the name travellers use.
            candidates.append((0 if "110202" in kind else 1, distance, _text(aoi.get("name"))))
    if not candidates:
        for poi in entry.get("pois") or []:
            if not isinstance(poi, dict):
                continue
            kind = str(poi.get("type") or "")
            distance = _float(poi.get("distance"))
            if distance <= 100 and kind.startswith(_SCENIC_POI_PREFIXES):
                candidates.append((2, distance, _text(poi.get("name"))))
    for _rank, _distance, name in sorted(candidates):
        cleaned = _clean_spot(name, city)
        if cleaned:
            return cleaned
    return None


def _clean_spot(name: str, city: str | None) -> str | None:
    value = re.sub(r"[（(][^）)]*[）)]", "", name).strip()
    value = value.split("-")[0].strip()
    stripped = _SPOT_SUFFIX.sub("", value)
    if len(stripped) >= 2:
        value = stripped
    # 香格里拉虎跳峡 → 虎跳峡, while 大理古城 keeps its name.
    if city and value.startswith(city) and len(value) - len(city) >= 3:
        value = value[len(city):]
    if len(value) < 2 or len(value) > 12:
        return None
    return value


def _time_key(photos: list[Any], asset_id: str) -> tuple[int, str]:
    for index, photo in enumerate(photos):
        if str(photo.asset_id) == asset_id:
            taken = photo_time(photo)
            return (0, taken.isoformat()) if taken else (1, f"{index:04d}")
    return (2, asset_id)


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _float(value: object) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float("inf")
