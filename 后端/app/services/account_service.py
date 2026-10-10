"""Real registration, password verification and revocable login sessions."""

from collections import deque
from datetime import timedelta, timezone
from functools import lru_cache
import hashlib
import re
import secrets
from threading import Lock
import time
from uuid import uuid4

from pwdlib import PasswordHash
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import AuthenticationError, InvalidParamError, RateLimitError
from app.db import accounts
from app.models.account import Account, AccountBase, LoginSession, PlanningMediaAccess
from app.models.base import utcnow

_passwords = PasswordHash.recommended()
_username_pattern = re.compile(r"[A-Za-z0-9_\-\u4e00-\u9fff]{2,24}")
_rate_lock = Lock()
_attempts: dict[tuple[str, str], deque[float]] = {}


def normalize_username(username: str) -> tuple[str, str]:
    value = username.strip()
    if not _username_pattern.fullmatch(value):
        raise InvalidParamError("用户名需为 2–24 个字，支持中文、字母、数字、下划线和短横线")
    return value, value.casefold()


def validate_password(password: str) -> None:
    if not 8 <= len(password) <= 128 or password.isspace():
        raise InvalidParamError("密码需为 8–128 个字符")


def check_attempts(action: str, client: str) -> None:
    now = time.monotonic()
    with _rate_lock:
        for key in list(_attempts):
            if not _attempts[key] or now - _attempts[key][-1] >= 60:
                del _attempts[key]
        key = action, client
        history = _attempts.setdefault(key, deque())
        while history and now - history[0] >= 60:
            history.popleft()
        if len(history) >= (5 if action == "register" else 30):
            raise RateLimitError("操作过于频繁，请稍后再试")
        history.append(now)


@lru_cache(maxsize=1)
def _dummy_hash() -> str:
    return _passwords.hash(secrets.token_urlsafe(24))


def ensure_accounts() -> None:
    """Create only identity tables; retain the current demo user's travel ID."""
    AccountBase.metadata.create_all(accounts.engine)
    username, key = normalize_username(settings.AUTH_DEMO_USERNAME)
    with Session(accounts.engine) as session:
        if session.get(Account, settings.DEFAULT_USER_ID) is not None:
            return
        password = settings.AUTH_DEMO_PASSWORD or secrets.token_urlsafe(24)
        validate_password(password)
        session.add(Account(
            id=settings.DEFAULT_USER_ID, username=username, username_key=key,
            password_hash=_passwords.hash(password), is_demo=True,
        ))
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            if session.get(Account, settings.DEFAULT_USER_ID) is None:
                raise RuntimeError("演示用户名已被占用，请检查 AUTH_DEMO_USERNAME") from None


def public_account(account: Account, *, read_only: bool = False) -> dict:
    return {"id": account.id, "username": account.username, "isDemo": account.is_demo,
            "readOnly": read_only}


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _new_login(session: Session, account: Account, *, read_only: bool = False) -> dict:
    now = utcnow()
    token, media_token = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    expires = now + timedelta(days=max(1, min(settings.AUTH_SESSION_DAYS, 365)))
    session.execute(delete(LoginSession).where(LoginSession.expires_at <= now))
    active = list(session.scalars(select(LoginSession).where(
        LoginSession.user_id == account.id,
        LoginSession.read_only == read_only,
    ).order_by(LoginSession.created_at.desc())))
    for old in active[19:]:
        session.delete(old)
    session.add(LoginSession(
        token_hash=_token_hash(token), media_token_hash=_token_hash(media_token),
        user_id=account.id, expires_at=expires, read_only=read_only,
    ))
    session.commit()
    return {
        "user": public_account(account, read_only=read_only), "token": token, "mediaToken": media_token,
        "expiresAt": expires.isoformat(),
    }


def register(username: str, password: str) -> dict:
    username, key = normalize_username(username)
    validate_password(password)
    with Session(accounts.engine) as session:
        if session.scalar(select(Account).where(Account.username_key == key)) is not None:
            raise InvalidParamError("这个用户名已被使用，请换一个")
        account = Account(
            id="user_" + uuid4().hex, username=username, username_key=key,
            password_hash=_passwords.hash(password), is_demo=False,
        )
        session.add(account)
        try:
            session.flush()
        except IntegrityError:
            session.rollback()
            raise InvalidParamError("这个用户名已被使用，请换一个") from None
        return _new_login(session, account)


def login(username: str, password: str) -> dict:
    _, key = normalize_username(username)
    validate_password(password)
    with Session(accounts.engine) as session:
        account = session.scalar(select(Account).where(Account.username_key == key))
        matches = _passwords.verify(password, account.password_hash if account else _dummy_hash())
        if account is None or not matches:
            raise InvalidParamError("用户名或密码不正确")
        return _new_login(session, account)


def demo_login() -> dict:
    if not settings.AUTH_DEMO_LOGIN_ENABLED:
        raise InvalidParamError("演示账号体验入口已关闭")
    with Session(accounts.engine) as session:
        account = session.get(Account, settings.DEFAULT_USER_ID)
        if account is None or not account.is_demo:
            raise AuthenticationError("演示账号尚未初始化，请重启服务")
        return _new_login(session, account, read_only=True)


def authenticate(token: str | None, *, media_only: bool = False) -> dict:
    if not token or len(token) > 128:
        raise AuthenticationError("请先登录")
    column = LoginSession.media_token_hash if media_only else LoginSession.token_hash
    with Session(accounts.engine) as session:
        login_session = session.scalar(select(LoginSession).where(column == _token_hash(token)))
        if login_session is None:
            raise AuthenticationError("登录已失效，请重新登录")
        expires = login_session.expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        if expires <= utcnow():
            raise AuthenticationError("登录已过期，请重新登录")
        account = session.get(Account, login_session.user_id)
        if account is None:
            raise AuthenticationError("账号不存在，请重新登录")
        return public_account(account, read_only=login_session.read_only)


def logout(token: str | None) -> None:
    if not token or len(token) > 128:
        return
    with Session(accounts.engine) as session:
        session.execute(delete(LoginSession).where(LoginSession.token_hash == _token_hash(token)))
        session.commit()


def grant_planning_media(user_id: str, payload: dict) -> None:
    data = payload.get("itinerary") or payload.get("itinerary_data") or payload.get("itineraryData") or {}
    paths = {
        image for day in data.get("itinerary", [])
        for item in day.get("daily_maps", [])
        if isinstance(image := item.get("image_url"), str)
        and image.startswith("/static/images/daily-maps/")
    }
    if not paths:
        return
    with Session(accounts.engine) as session:
        for path in paths:
            if session.get(PlanningMediaAccess, (user_id, path)) is not None:
                continue
            try:
                with session.begin_nested():
                    session.add(PlanningMediaAccess(user_id=user_id, relative_path=path))
                    session.flush()
            except IntegrityError:
                pass  # Another request has already granted this same map.
        session.commit()


def can_read_planning_media(user_id: str, path: str) -> bool:
    with Session(accounts.engine) as session:
        return session.get(PlanningMediaAccess, (user_id, path)) is not None
