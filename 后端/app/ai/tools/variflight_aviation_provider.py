"""VariFlight Aviation MCP adapter for the selected flight tools."""

from __future__ import annotations

from urllib.parse import urlsplit

from app.ai.tools.variflight_tripmatch_provider import (
    TripmatchCallResult,
    call_streamable_tool_sync,
)
from app.core.config import settings

PROVIDER = "variflight_aviation_mcp"
TOOL_SEARCH_FLIGHTS_BY_DEP_ARR = "searchFlightsByDepArr"
TOOL_GET_FLIGHT_TRANSFER_INFO = "getFlightTransferInfo"
TOOL_SEARCH_FLIGHT_ITINERARIES = "searchFlightItineraries"


def is_configured() -> bool:
    return bool(
        settings.TOOLS_ENABLED
        and settings.VARIFLIGHT_AVIATION_MCP_ENABLED
        and settings.VARIFLIGHT_AVIATION_MCP_URL.strip()
        and settings.VARIFLIGHT_API_KEY.strip()
    )


def configuration_status() -> str:
    if not settings.TOOLS_ENABLED or not settings.VARIFLIGHT_AVIATION_MCP_ENABLED:
        return "disabled"
    if not settings.VARIFLIGHT_AVIATION_MCP_URL.strip():
        return "endpoint_missing"
    if not settings.VARIFLIGHT_API_KEY.strip():
        return "api_key_missing"
    return "configured"


def endpoint_identity() -> str:
    parts = urlsplit(settings.VARIFLIGHT_AVIATION_MCP_URL.strip())
    return f"{parts.scheme}://{parts.netloc}{parts.path}"


def search_flight_itineraries_sync(
    dep_city_code: str, dep_date: str, arr_city_code: str
) -> TripmatchCallResult:
    return call_streamable_tool_sync(
        TOOL_SEARCH_FLIGHT_ITINERARIES,
        {
            "depCityCode": dep_city_code,
            "depDate": dep_date,
            "arrCityCode": arr_city_code,
        },
        enabled=settings.TOOLS_ENABLED and settings.VARIFLIGHT_AVIATION_MCP_ENABLED,
        endpoint=settings.VARIFLIGHT_AVIATION_MCP_URL,
        api_key=settings.VARIFLIGHT_API_KEY,
        timeout_seconds=settings.VARIFLIGHT_AVIATION_TIMEOUT_SECONDS,
        provider_label="Aviation",
    )


def search_flights_by_dep_arr_sync(
    *,
    date: str,
    dep: str | None = None,
    depcity: str | None = None,
    arr: str | None = None,
    arrcity: str | None = None,
) -> TripmatchCallResult:
    arguments = {
        "date": date,
        **({"dep": dep} if dep else {}),
        **({"depcity": depcity} if depcity else {}),
        **({"arr": arr} if arr else {}),
        **({"arrcity": arrcity} if arrcity else {}),
    }
    return call_streamable_tool_sync(
        TOOL_SEARCH_FLIGHTS_BY_DEP_ARR,
        arguments,
        enabled=settings.TOOLS_ENABLED and settings.VARIFLIGHT_AVIATION_MCP_ENABLED,
        endpoint=settings.VARIFLIGHT_AVIATION_MCP_URL,
        api_key=settings.VARIFLIGHT_API_KEY,
        timeout_seconds=settings.VARIFLIGHT_AVIATION_TIMEOUT_SECONDS,
        provider_label="Aviation",
    )


def get_flight_transfer_info_sync(
    depcity: str, arrcity: str, depdate: str
) -> TripmatchCallResult:
    return call_streamable_tool_sync(
        TOOL_GET_FLIGHT_TRANSFER_INFO,
        {"depcity": depcity, "arrcity": arrcity, "depdate": depdate},
        enabled=settings.TOOLS_ENABLED and settings.VARIFLIGHT_AVIATION_MCP_ENABLED,
        endpoint=settings.VARIFLIGHT_AVIATION_MCP_URL,
        api_key=settings.VARIFLIGHT_API_KEY,
        timeout_seconds=settings.VARIFLIGHT_AVIATION_TIMEOUT_SECONDS,
        provider_label="Aviation",
    )
