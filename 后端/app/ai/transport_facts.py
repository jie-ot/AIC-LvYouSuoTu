"""One transport contract for research, synthesis and deterministic checks."""
from __future__ import annotations

from datetime import datetime
import re
from typing import Any


def _lookup(fact: dict, *names: str) -> str | None:
    normalized = {re.sub(r"[^a-z0-9]", "", str(key).lower()): value for key, value in fact.items()}
    for name in names:
        value = normalized.get(re.sub(r"[^a-z0-9]", "", name.lower()))
        if isinstance(value, (str, int)) and str(value).strip():
            return str(value).strip()
    return None


def _local_datetime(value: str | None) -> str | None:
    if not value or not re.search(r"[T\s]\d{1,2}:\d{2}", value):
        return None
    try:
        # Provider datetimes are local to the departure/arrival airport. Keep
        # the local clock and date; do not replace a timetable with a forecast.
        return datetime.fromisoformat(value.replace("Z", "+00:00")).strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return None


def normalize_transport_fact(fact: dict[str, Any], tool: str | None = None) -> dict[str, Any]:
    result = dict(fact)
    tool = tool or str(fact.get("tool") or "")
    flight = tool in {"searchFlightsByDepArr", "getFlightTransferInfo", "searchFlightItineraries", "getFlightAndTrainTransferInfo"}
    rail = tool == "searchTrainTickets"
    if not (flight or rail):
        return result
    number = _lookup(fact, "flight_no", "flight_number") if flight else _lookup(fact, "train_no", "station_train_code", "train_code")
    if number:
        result["flight_no" if flight else "train_no"] = number.upper()
    for target, aliases in (
        ("depart_datetime", ("depart_datetime", "FlightDeptimePlanDate", "scheduled_departure_datetime")),
        ("arrive_datetime", ("arrive_datetime", "FlightArrtimePlanDate", "scheduled_arrival_datetime")),
    ):
        value = _local_datetime(_lookup(fact, *aliases))
        if value:
            result[target] = value
    for target, aliases in (
        ("depart_time", ("depart_time", "departure_time", "start_time")),
        ("arrive_time", ("arrive_time", "arrival_time")),
    ):
        value = _lookup(fact, *aliases)
        if value and re.fullmatch(r"\d{1,2}:\d{2}(?::\d{2})?", value):
            hour, minute = value.split(":")[:2]
            if 0 <= int(hour) < 24 and 0 <= int(minute) < 60:
                result[target] = f"{int(hour):02d}:{minute}"
    for target, aliases in (
        ("depart_city", ("depart_city", "FlightDep")),
        ("arrive_city", ("arrive_city", "FlightArr")),
        ("depart_airport", ("depart_airport", "FlightDepAirport")),
        ("arrive_airport", ("arrive_airport", "FlightArrAirport")),
    ):
        if value := _lookup(fact, *aliases):
            result[target] = value
    return result
