"""
Finoks — SQLAlchemy 2 engine and session factory (SQLite by default).
"""

from __future__ import annotations

import os
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


def _database_url() -> str:
    return os.getenv("FINOKS_DATABASE_URL", "sqlite:///./finoks.db")


class Base(DeclarativeBase):
    """Declarative base for Finoks ORM models."""


_engine = create_engine(
    _database_url(),
    connect_args={"check_same_thread": False} if _database_url().startswith("sqlite") else {},
    future=True,
)

SessionLocal = sessionmaker(bind=_engine, autoflush=False, autocommit=False, expire_on_commit=False, future=True)


def get_engine():
    """Return the shared SQLAlchemy engine."""

    return _engine


def get_db() -> Iterator[Session]:
    """FastAPI dependency: yield a database session and ensure cleanup."""

    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Create tables if they do not exist (imports models for metadata registration)."""

    import models  # noqa: F401 — register tables on Base.metadata

    Base.metadata.create_all(bind=_engine)
