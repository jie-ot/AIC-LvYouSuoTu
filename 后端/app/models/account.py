"""Identity metadata is separate from the shareable travel/demo database."""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.models.base import utcnow


class AccountBase(DeclarativeBase):
    pass


class Account(AccountBase):
    __tablename__ = "accounts"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    username: Mapped[str] = mapped_column(String, nullable=False)
    username_key: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String, nullable=False)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class LoginSession(AccountBase):
    __tablename__ = "login_sessions"

    token_hash: Mapped[str] = mapped_column(String, primary_key=True)
    media_token_hash: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    user_id: Mapped[str] = mapped_column(ForeignKey("accounts.id"), index=True)
    read_only: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PlanningMediaAccess(AccountBase):
    """Maps returned by planning before the itinerary has been saved."""

    __tablename__ = "planning_media_access"

    user_id: Mapped[str] = mapped_column(String, primary_key=True)
    relative_path: Mapped[str] = mapped_column(String, primary_key=True)
