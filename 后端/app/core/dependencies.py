"""Shared server-verified identity for all private business routes."""

from fastapi import Depends, Request
from app.core.exceptions import ReadOnlyError

from app.services import account_service


def bearer_token(request: Request) -> str | None:
    scheme, _, token = request.headers.get("Authorization", "").partition(" ")
    return token if scheme.casefold() == "bearer" else None


def get_current_account(request: Request) -> dict:
    account = account_service.authenticate(bearer_token(request))
    if account["readOnly"] and request.method not in {"GET", "HEAD", "OPTIONS"}:
        raise ReadOnlyError("演示账号仅供浏览，请注册自己的账号后操作")
    return account


def get_current_user_id(account: dict = Depends(get_current_account)) -> str:
    return account["id"]
