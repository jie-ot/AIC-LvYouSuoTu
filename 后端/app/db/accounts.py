"""Local identity persistence, separate from the existing travel schema."""

from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import make_url

from app.core.config import settings


def _build_engine():
    url = make_url(settings.AUTH_DATABASE_URL)
    travel_url = make_url(settings.DATABASE_URL)
    if url == travel_url or (
        url.get_backend_name() == travel_url.get_backend_name() == "sqlite"
        and url.database not in {None, ":memory:"}
        and travel_url.database not in {None, ":memory:"}
        and Path(url.database).resolve() == Path(travel_url.database).resolve()
    ):
        raise ValueError("AUTH_DATABASE_URL 必须与旅行数据库分开")
    if url.get_backend_name() == "sqlite" and url.database not in {None, ":memory:"}:
        Path(url.database).parent.mkdir(parents=True, exist_ok=True)
    return create_engine(
        url,
        connect_args={"check_same_thread": False} if url.get_backend_name() == "sqlite" else {},
    )


engine = _build_engine()


@event.listens_for(engine, "connect")
def _enable_foreign_keys(connection, record):  # noqa: ANN001
    if engine.dialect.name == "sqlite":
        connection.execute("PRAGMA foreign_keys=ON")
