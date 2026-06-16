"""
SQLAlchemy database setup.

Why SQLite for now:
  - Zero-infrastructure: no separate DB process, works in Docker with a bind-mount volume
  - SQLAlchemy's abstraction means switching to PostgreSQL is a one-line change
    in Settings.database_url (e.g. postgresql+psycopg2://user:pass@host/db)
  - The repository pattern in app/repositories/ ensures no raw SQL escapes this layer

check_same_thread=False:
  Required for SQLite + FastAPI because SQLite connections are not thread-safe by
  default, but FastAPI runs request handlers in a thread pool.  The connect_arg
  tells SQLite to allow cross-thread use; SQLAlchemy's connection pool manages
  safety above that level.
"""
import os
from functools import lru_cache
from typing import Generator

from sqlalchemy import create_engine, Engine
from sqlalchemy.orm import sessionmaker, Session, DeclarativeBase

from app.core.config import get_settings


class Base(DeclarativeBase):
    pass


def _make_engine() -> Engine:
    settings = get_settings()
    db_url = settings.database_url
    # Ensure the directory exists for SQLite file-based databases
    if db_url.startswith("sqlite:///"):
        db_path = db_url.replace("sqlite:///", "")
        db_dir = os.path.dirname(db_path)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)
    connect_args = {"check_same_thread": False} if "sqlite" in db_url else {}
    return create_engine(db_url, connect_args=connect_args)


@lru_cache
def get_engine() -> Engine:
    return _make_engine()


@lru_cache
def get_session_factory() -> sessionmaker:
    return sessionmaker(autocommit=False, autoflush=False, bind=get_engine())


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency — yields a DB session and closes it when the request ends."""
    factory = get_session_factory()
    db = factory()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Create all tables. Called once at application startup."""
    from app.models import scan_document as _      # noqa: F401 — scan OCR table
    from app.models import nis_master as _nm       # noqa: F401 — NIS person registry
    from app.models import document_metadata as _dm  # noqa: F401 — NIS document metadata
    Base.metadata.create_all(bind=get_engine())
