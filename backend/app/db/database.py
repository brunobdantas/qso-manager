from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import os
import sys

# Add backend to path for proper imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.config import settings
from app.core.runtime import ensure_runtime_dirs

ensure_runtime_dirs()


def _ensure_sqlite_parent(database_url: str) -> None:
    prefix = "sqlite:///"
    if not database_url.startswith(prefix):
        return
    raw_path = database_url[len(prefix):]
    if not raw_path or raw_path == ":memory:":
        return
    Path(raw_path).expanduser().parent.mkdir(parents=True, exist_ok=True)


_ensure_sqlite_parent(settings.database_url)

engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False}  # Needed for SQLite
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    """Dependency for getting database sessions."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
