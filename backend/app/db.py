"""Database wiring. This is done for you - you should not need to change it."""

import os

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql+psycopg://aa:aa@localhost:5432/surveys"
)

engine = create_engine(DATABASE_URL, pool_pre_ping=True, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    """Base class for your ORM models."""


def get_session():
    """FastAPI dependency. Yields a session and always closes it."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
