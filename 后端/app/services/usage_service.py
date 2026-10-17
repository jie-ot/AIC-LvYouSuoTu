"""Persistent, concurrency-safe lifetime allowances for ordinary accounts."""

from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator, Literal
from uuid import uuid4

from sqlalchemy import delete, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import AuthenticationError, UsageLimitError
from app.db import accounts
from app.models.account import Account, FeatureUsage

Feature = Literal["planning", "creation"]
USAGE_LIMIT = 3


@dataclass
class UsageReservation:
    id: str | None
    completed: bool = False

    def consume(self) -> None:
        if self.id is None or self.completed:
            return
        with Session(accounts.engine) as session:
            session.execute(update(FeatureUsage).where(
                FeatureUsage.id == self.id,
            ).values(completed=True))
            session.commit()
        self.completed = True

    def release(self) -> None:
        if self.id is None or self.completed:
            return
        with Session(accounts.engine) as session:
            session.execute(delete(FeatureUsage).where(
                FeatureUsage.id == self.id,
                FeatureUsage.completed.is_(False),
            ))
            session.commit()


def _reserve(user_id: str, feature: Feature) -> UsageReservation:
    with Session(accounts.engine) as session:
        account = session.get(Account, user_id)
        if account is None:
            raise AuthenticationError("账号不存在，请重新登录")
        if account.is_demo:
            return UsageReservation(None)

        # The unique slot constraint arbitrates competing requests, including
        # requests handled by different server processes. No lock/transaction
        # is held while the model runs. Failed work releases its reservation.
        for slot in range(USAGE_LIMIT):
            reservation_id = uuid4().hex
            try:
                with session.begin_nested():
                    session.add(FeatureUsage(
                        id=reservation_id, user_id=user_id, feature=feature, slot=slot,
                    ))
                    session.flush()
            except IntegrityError:
                continue
            session.commit()
            return UsageReservation(reservation_id)
    raise UsageLimitError("超出使用上限")


@contextmanager
def reserve(user_id: str, feature: Feature) -> Iterator[UsageReservation]:
    reservation = _reserve(user_id, feature)
    try:
        yield reservation
    finally:
        reservation.release()
