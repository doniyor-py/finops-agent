"""
Finoks — SQLAlchemy models.

Persistence is intentionally minimal in this phase: the in-memory agent runtime
(see ``agent.py``) holds invoice / event / autonomy state. Only the user table is
relied upon for JWT auth.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


class User(Base):
    """Application user with credentials for JWT auth."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
