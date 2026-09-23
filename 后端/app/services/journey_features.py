"""Spatio-temporal and visual features of one trip, computed before any copywriting.

Everything here is measured from camera time, GPS, reverse-geocoded places,
pixel colours and the per-photo visual analysis. The persona engine turns these
numbers into axes; the language model only ever sees the results.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime

from app.ai.schemas import PhotoAnalysisItem, PhotoAnalysisResult
from app.models import dto
from app.services import place_service
from app.services.palette_service import TripPalette
from app.services.place_service import GeoPoint, PhotoPlace, TripPlaces

NATURE_TAGS = frozenset({"nature", "coast", "mountain"})
URBAN_TAGS = frozenset({"city", "street", "culture", "food"})


@dataclass(frozen=True)
class JourneyPhoto:
    asset_id: str
    analysis: PhotoAnalysisItem
    taken: datetime | None
    point: GeoPoint | None
    place: PhotoPlace | None

    @property
    def tags(self) -> set[str]:
        return set(self.analysis.scene_tags)

    @property
    def place_label(self) -> str | None:
        if self.place and self.place.label:
            return self.place.label
        guess = (self.analysis.location_guess or "").strip()
        return guess if guess and "未知" not in guess else None

    @property
    def city(self) -> str | None:
        if self.place and self.place.city:
            return self.place.city
        return self.place_label


@dataclass
class JourneyFeatures:
    photos: list[JourneyPhoto]
    places: TripPlaces
    palette: TripPalette
    destination: str | None = None
    route: list[str] = field(default_factory=list)
    spots: list[str] = field(default_factory=list)
    start_date: date | None = None
    end_date: date | None = None
    path_km: float | None = None
    span: tuple[JourneyPhoto, JourneyPhoto] | None = None
    farthest: tuple[float, JourneyPhoto] | None = None
    earliest: JourneyPhoto | None = None
    latest: JourneyPhoto | None = None
    mean_hour_offset: float | None = None
    max_altitude: tuple[float, JourneyPhoto] | None = None
    busiest_day: tuple[date, int] | None = None
    scene_counts: Counter = field(default_factory=Counter)
    scale_counts: Counter = field(default_factory=Counter)
    nature_count: int = 0
    urban_count: int = 0
    gps_share: float = 0.0
    time_share: float = 0.0

    @property
    def photo_count(self) -> int:
        return len(self.photos)

    @property
    def day_count(self) -> int | None:
        if self.start_date and self.end_date:
            return (self.end_date - self.start_date).days + 1
        return None

    @property
    def stop_count(self) -> int:
        return len(self.route)

    def visited_names(self) -> set[str]:
        names = {name for name in (self.destination, *self.route, *self.spots) if name}
        names.update(self.places.provinces)
        return names


def build_features(
    analysis: PhotoAnalysisResult,
    uploaded: list[dto.UploadedPhoto],
    places: TripPlaces,
    palette: TripPalette,
) -> JourneyFeatures:
    by_id = {photo.asset_id: photo for photo in uploaded}
    photos: list[JourneyPhoto] = []
    for index, item in enumerate(analysis.photos):
        if item.suitability == "unsuitable":
            continue
        source = by_id.get(item.asset_id)
        photos.append(JourneyPhoto(
            asset_id=item.asset_id,
            analysis=item,
            taken=place_service.photo_time(source) if source else None,
            point=place_service.photo_point(source) if source else None,
            place=places.by_asset.get(item.asset_id),
        ))
    order = {photo.asset_id: index for index, photo in enumerate(photos)}
    photos.sort(key=lambda photo: (photo.taken is None, photo.taken or datetime.min, order[photo.asset_id]))

    features = JourneyFeatures(photos=photos, places=places, palette=palette)
    total = max(1, len(photos))
    features.gps_share = sum(photo.point is not None for photo in photos) / total
    features.time_share = sum(photo.taken is not None for photo in photos) / total
    _add_places(features, analysis)
    _add_dates(features, analysis)
    _add_trajectory(features)
    _add_rhythm(features)
    for photo in photos:
        features.scene_counts.update(photo.tags)
        features.scale_counts[photo.analysis.shot_scale or _inferred_scale(photo.tags)] += 1
        features.nature_count += bool(photo.tags & NATURE_TAGS)
        features.urban_count += bool(photo.tags & URBAN_TAGS)
    return features


def _add_places(features: JourneyFeatures, analysis: PhotoAnalysisResult) -> None:
    places = features.places
    if places.resolved:
        features.destination = places.destination
        features.route = list(places.route)
        features.spots = list(places.spots)
        return
    # No usable GPS: fall back to what the vision model read from landmarks,
    # visible text and the user's own description.
    guesses = [photo.place_label for photo in features.photos if photo.place_label]
    features.route = list(dict.fromkeys(guesses))[:6]
    overall = (analysis.overall_location or "").strip()
    if overall and "未知" not in overall:
        features.destination = overall
    elif guesses:
        features.destination = Counter(guesses).most_common(1)[0][0]


def _add_dates(features: JourneyFeatures, analysis: PhotoAnalysisResult) -> None:
    days = [photo.taken.date() for photo in features.photos if photo.taken]
    if not days:
        for value in (analysis.start_date, analysis.end_date):
            try:
                days.append(date.fromisoformat(value or ""))
            except ValueError:
                continue
    if days:
        features.start_date, features.end_date = min(days), max(days)
    per_day = Counter(photo.taken.date() for photo in features.photos if photo.taken)
    if per_day:
        features.busiest_day = max(per_day.items(), key=lambda item: (item[1], -item[0].toordinal()))


def _add_trajectory(features: JourneyFeatures) -> None:
    located = [photo for photo in features.photos if photo.point is not None]
    # Photos are already in capture order. The distance people read is the
    # straight line from the earliest geotagged frame to the latest one,
    # not the sum of every step in between.
    timed = [photo for photo in located if photo.taken is not None]
    if len(timed) >= 2:
        start, end = timed[0], timed[-1]
        features.span = (start, end)
        features.path_km = place_service.haversine_km(start.point, end.point)  # type: ignore[arg-type]
    if len(located) >= 2:
        origin = timed[0].point if timed else located[0].point
        distance, photo = max(
            ((place_service.haversine_km(origin, item.point), item) for item in located[1:]),  # type: ignore[arg-type]
            key=lambda pair: pair[0],
        )
        features.farthest = (distance, photo)
    altitudes = [(photo.point.altitude, photo) for photo in located if photo.point and photo.point.altitude]
    if altitudes:
        features.max_altitude = max(altitudes, key=lambda pair: pair[0])


def _add_rhythm(features: JourneyFeatures) -> None:
    timed = [photo for photo in features.photos if photo.taken]
    if not timed:
        return

    def clock(photo: JourneyPhoto) -> float:
        taken = photo.taken
        assert taken is not None
        value = taken.hour + taken.minute / 60
        # After-midnight shots still belong to the evening they started in.
        return value + 24 if value < 4 else value

    features.earliest = min(timed, key=clock)
    features.latest = max(timed, key=clock)
    features.mean_hour_offset = sum(clock(photo) - 13 for photo in timed) / len(timed)


def _inferred_scale(tags: set[str]) -> str:
    if tags & {"food"}:
        return "close"
    if tags & {"mountain", "coast", "nature"}:
        return "wide"
    return "medium"
