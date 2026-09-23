"""Tool-internal schemas used by the planning fact pipeline."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

FactStatus = Literal[
    "ok",
    "unknown",
    "timeout",
    "provider_not_connected",
]


class ToolCallResult(BaseModel):
    tool_name: str
    provider: str
    status: FactStatus
    latency_ms: int | None = None
    error_code: str | None = None


class RouteStepFact(BaseModel):
    instruction: str | None = None
    road_name: str | None = None
    distance_km: float | None = None
    duration_minutes: int | None = None
    transport: str | None = None
    departure_stop: str | None = None
    arrival_stop: str | None = None
    line_name: str | None = None
    action: str | None = None
    assistant_action: str | None = None
    first_time: str | None = None
    last_time: str | None = None
    polyline: str | None = None


class RouteAlternativeFact(BaseModel):
    distance_km: float | None = None
    duration_minutes: int | None = None
    walking_distance_km: float | None = None
    transfers: int | None = None
    cost_yuan: float | None = None
    taxi_cost_yuan: float | None = None
    tolls_yuan: float | None = None
    toll_distance_km: float | None = None
    traffic_lights: int | None = None
    night_service: bool | None = None
    restriction: str | None = None
    polyline: str | None = None
    steps: list[RouteStepFact] = Field(default_factory=list)


class RouteFact(BaseModel):  # amap_route
    origin: str
    destination: str
    mode: Literal["driving", "transit", "walking", "bicycling"]
    distance_km: float | None
    duration_minutes: int | None
    status: FactStatus
    origin_location: str | None = None
    destination_location: str | None = None
    origin_poi_id: str | None = None
    destination_poi_id: str | None = None
    waypoint_locations: list[str] = Field(default_factory=list)
    strategy: int | None = None
    alternatives: list[RouteAlternativeFact] = Field(default_factory=list)


class WeatherFact(BaseModel):  # amap_weather
    city: str
    date: str  # YYYY-MM-DD
    summary: str | None  # e.g. "多云 18-26℃"
    status: FactStatus
    day_weather: str | None = None
    night_weather: str | None = None
    day_temp_c: float | None = None
    night_temp_c: float | None = None
    day_wind: str | None = None
    night_wind: str | None = None
    day_power: str | None = None
    night_power: str | None = None
    report_time: str | None = None


class PoiFact(BaseModel):  # amap_poi_search / amap_geocode
    name: str
    address: str | None
    location: str | None  # "lng,lat"
    category: str | None
    status: FactStatus
    poi_id: str | None = None
    parent_id: str | None = None
    typecode: str | None = None
    adcode: str | None = None
    citycode: str | None = None
    city_name: str | None = None
    district_name: str | None = None
    distance_m: int | None = None
    business_area: str | None = None
    opening_hours_today: str | None = None
    opening_hours_week: str | None = None
    tel: str | None = None
    tag: str | None = None
    rating: float | None = None
    cost_yuan: float | None = None
    entrance_location: str | None = None
    exit_location: str | None = None
    photo_url: str | None = None


class TravelFactPack(BaseModel):
    request_id: str
    generated_at: str  # ISO 8601
    routes: list[RouteFact] = []
    weather: list[WeatherFact] = []
    pois: list[PoiFact] = []
    tool_calls: list[ToolCallResult] = []
