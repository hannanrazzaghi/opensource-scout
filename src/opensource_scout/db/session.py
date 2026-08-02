"""SQLite engine and session factory.

Alembic (see ``alembic/``) owns schema creation and migration for real usage;
:func:`create_schema` is provided for tests and quick local setup where
running full migrations would be unnecessary overhead.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from opensource_scout.db.models import Base


def build_engine(database_url: str) -> Engine:
    engine = create_engine(database_url, future=True)

    if database_url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def _set_sqlite_pragmas(dbapi_connection, _connection_record) -> None:  # noqa: ANN001
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.close()

    return engine


def create_schema(engine: Engine) -> None:
    """Create all tables directly from the ORM metadata. Used by tests and
    ``oss init`` for a fresh local database; production upgrades should go
    through Alembic (``uv run alembic upgrade head``)."""
    Base.metadata.create_all(engine)


def build_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)


@contextmanager
def session_scope(session_factory: sessionmaker[Session]) -> Iterator[Session]:
    """Provide a transactional scope: commits on success, rolls back and
    re-raises on any exception."""
    session = session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def ensure_database(database_path: Path, database_url: str) -> Engine:
    """Ensure the parent directory exists, build the engine, and create the
    schema if the database file doesn't exist yet."""
    database_path.parent.mkdir(parents=True, exist_ok=True)
    is_new = not database_path.exists()
    engine = build_engine(database_url)
    if is_new:
        create_schema(engine)
    return engine
