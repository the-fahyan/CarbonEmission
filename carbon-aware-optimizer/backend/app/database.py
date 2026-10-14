"""SQLite engine/session management.

A `Database` object owns the engine so tests can create isolated databases.
Schema is created with `create_all` at startup; to add migrations later,
introduce Alembic and replace `init_schema` (models stay unchanged).
"""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    pass


class Database:
    def __init__(self, url: str) -> None:
        if url.startswith("sqlite:///") and ":memory:" not in url:
            Path(url.replace("sqlite:///", "", 1)).parent.mkdir(parents=True, exist_ok=True)
        self.engine: Engine = create_engine(
            url, connect_args={"check_same_thread": False, "timeout": 15}
        )

        @event.listens_for(self.engine, "connect")
        def _pragmas(dbapi_conn, _):  # noqa: ANN001
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")  # enforce FK constraints
            cur.execute("PRAGMA journal_mode=WAL")  # readers don't block the writer
            cur.execute("PRAGMA busy_timeout=15000")
            cur.close()

        self.SessionLocal = sessionmaker(bind=self.engine, expire_on_commit=False)

    def init_schema(self) -> None:
        from app import models  # noqa: F401  (register tables)

        Base.metadata.create_all(self.engine)

    @contextmanager
    def session(self) -> Iterator[Session]:
        """Transactional scope: commit on success, roll back on error."""
        s = self.SessionLocal()
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    def dispose(self) -> None:
        self.engine.dispose()
