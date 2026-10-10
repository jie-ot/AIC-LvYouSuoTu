"""Keep existing media paths while checking ownership at file reads."""

import os

from fastapi import Request
from fastapi.staticfiles import StaticFiles
from sqlalchemy import Text, cast, or_
from sqlmodel import Session, select
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException

from app.core.dependencies import bearer_token
from app.core.exceptions import AuthenticationError
from app.db import session as travel_db
from app.models.discovery import DiscoveryPost
from app.models.file_asset import FileAsset
from app.models.plan import Plan
from app.services import account_service
from app.services.storage_service import DEFAULT_COVER_PATH


def _contains_path(value, path: str) -> bool:
    if isinstance(value, str):
        return value == path
    if isinstance(value, dict):
        return any(_contains_path(item, path) for item in value.values())
    if isinstance(value, list):
        return any(_contains_path(item, path) for item in value)
    return False


def _allowed(path: str, request: Request) -> bool:
    if path == DEFAULT_COVER_PATH:
        return True
    with Session(travel_db.engine) as session:
        asset = session.exec(select(FileAsset).where(FileAsset.relative_path == path)).first()
        if asset is not None and asset.status == "deleted":
            return False
        if asset is not None and asset.user_id == "system":
            return True
        published = session.exec(select(DiscoveryPost).where(
            DiscoveryPost.status == "published",
            or_(cast(DiscoveryPost.photos, Text).contains(path, autoescape=True),
                cast(DiscoveryPost.attachments, Text).contains(path, autoescape=True)),
        )).all()
        if any(_contains_path(post.photos, path) or _contains_path(post.attachments, path)
               for post in published):
            return True
        try:
            media_token = request.query_params.get("media_token")
            account = account_service.authenticate(
                media_token or bearer_token(request), media_only=bool(media_token),
            )
        except AuthenticationError:
            return False
        if asset is not None:
            return asset.user_id == account["id"]
        if path.startswith("/static/images/daily-maps/"):
            if account_service.can_read_planning_media(account["id"], path):
                return True
            plans = session.exec(select(Plan).where(
                Plan.user_id == account["id"],
                cast(Plan.itinerary_data, Text).contains(path, autoescape=True),
            )).all()
            return any(_contains_path(plan.itinerary_data, path) for plan in plans)
        return False


class PrivateStaticFiles(StaticFiles):
    async def get_response(self, path, scope):  # noqa: ANN001
        normalized = os.path.normpath(path).replace("\\", "/")
        if normalized.startswith("../") or normalized == "..":
            raise HTTPException(status_code=404)
        if not await run_in_threadpool(_allowed, "/static/" + normalized, Request(scope)):
            raise HTTPException(status_code=404)
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "private, no-store"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response
