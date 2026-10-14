from __future__ import annotations

from typing import Iterator

from fastapi import Request
from sqlalchemy.orm import Session


class Ctx:
    """Shared services hung on app.state."""
    def __init__(self, database, bus, clock, cfg, worker=None) -> None:
        self.database, self.bus, self.clock, self.cfg, self.worker = database, bus, clock, cfg, worker


def get_ctx(request: Request) -> Ctx:
    return request.app.state.ctx


def get_db(request: Request) -> Iterator[Session]:
    """Plain session; endpoints commit explicitly. Exceptions roll the transaction back."""
    s = request.app.state.ctx.database.SessionLocal()
    try:
        yield s
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()
