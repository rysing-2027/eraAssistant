"""Database utilities."""
from typing import Generator  # noqa: F401
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from contextlib import contextmanager
import os
import json


def _json_serializer(obj):
    """Custom JSON serializer that preserves Chinese characters."""
    return json.dumps(obj, ensure_ascii=False)


def _json_deserializer(s):
    """Custom JSON deserializer."""
    return json.loads(s)


# Database URL from environment, default to SQLite in data/ folder
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./data/era.db")

# Create engine with custom JSON serializer
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {},
    json_serializer=_json_serializer,
    json_deserializer=_json_deserializer,
    echo=False  # Set to True to see SQL queries
)

# Session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@contextmanager
def get_db() -> Generator[Session, None, None]:
    """Context manager for database sessions."""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def init_db():
    """Initialize database - create all tables."""
    from app.models.record import Base
    from app.models.ai_config import Base as AIConfigBase

    Base.metadata.create_all(bind=engine)
    AIConfigBase.metadata.create_all(bind=engine)
