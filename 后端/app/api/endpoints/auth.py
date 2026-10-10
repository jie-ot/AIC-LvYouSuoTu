"""Username/password registration and shared competition-demo login."""

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field

from app.core.config import settings
from app.core.dependencies import bearer_token, get_current_account
from app.core.responses import success
from app.services import account_service

router = APIRouter(prefix="/auth", tags=["auth"])


class Credentials(BaseModel):
    username: str = Field(min_length=2, max_length=24)
    password: str = Field(min_length=8, max_length=128)


def _prepare(request: Request, response: Response, action: str) -> None:
    response.headers["Cache-Control"] = "no-store"
    account_service.check_attempts(action, request.client.host if request.client else "unknown")


@router.get("/options")
def options(response: Response) -> dict:
    response.headers["Cache-Control"] = "no-store"
    return success({"demoEnabled": settings.AUTH_DEMO_LOGIN_ENABLED,
                    "demoUsername": settings.AUTH_DEMO_USERNAME})


@router.post("/register")
def register(data: Credentials, request: Request, response: Response) -> dict:
    _prepare(request, response, "register")
    return success(account_service.register(data.username, data.password))


@router.post("/login")
def login(data: Credentials, request: Request, response: Response) -> dict:
    _prepare(request, response, "login")
    return success(account_service.login(data.username, data.password))


@router.post("/demo")
def demo(request: Request, response: Response) -> dict:
    _prepare(request, response, "demo")
    return success(account_service.demo_login())


@router.get("/me")
def me(response: Response, account: dict = Depends(get_current_account)) -> dict:
    response.headers["Cache-Control"] = "no-store"
    return success(account)


@router.post("/logout")
def logout(request: Request, response: Response) -> dict:
    response.headers["Cache-Control"] = "no-store"
    account_service.logout(bearer_token(request))
    return success()
