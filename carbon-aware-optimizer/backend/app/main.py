"""FastAPI application factory + lifecycle (startup reconcile, worker start/stop)."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from app.api.deps import Ctx
from app.api.routes import router
from app.config import load_config
from app.database import Database
from app.services.event_bus import EventBus
from app.services.settings import SimClock, load_settings
from app.services.worker import WorkerService, reconcile_on_startup

log = logging.getLogger("app")


def create_app(database_url: str | None = None, start_worker: bool = True) -> FastAPI:
    cfg = load_config()
    database = Database(database_url or cfg.database_url)
    database.init_schema()
    bus = EventBus(cfg.event_buffer_size)
    clock = SimClock()
    worker = WorkerService(database, bus, clock, cfg.worker_tick_seconds)
    ctx = Ctx(database, bus, clock, cfg, worker)

    # Restore persisted simulation time and reconcile interrupted jobs (synchronously, before serving).
    with database.session() as db:
        speed = load_settings(db).simulation_speed
        clock.restore_after_restart(db, speed)
        interrupted = reconcile_on_startup(db, bus, clock.now())
        if interrupted:
            log.warning("Reconciled %d interrupted attempt(s)", interrupted)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        import asyncio
        bus.bind_loop(asyncio.get_running_loop())
        if start_worker:
            worker.start()
        yield
        await worker.stop()
        with database.session() as db:
            clock.persist_now(db)
        database.dispose()

    app = FastAPI(title="AI-Driven Smart Energy Load Optimizer", version="1.0.0", lifespan=lifespan,
                  description="Carbon-aware job scheduler proxy (SDG 13). Telemetry is manual/simulated.")
    app.state.ctx = ctx
    app.add_middleware(CORSMiddleware, allow_origins=cfg.frontend_origins, allow_methods=["*"], allow_headers=["*"])
    app.include_router(router)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError):
        details = [f"{'.'.join(str(p) for p in e['loc'][1:])}: {e['msg']}" for e in exc.errors()]
        return JSONResponse(status_code=422, content={"error": "validation_error",
                                                      "message": "Request validation failed.", "details": details})

    from fastapi import HTTPException

    @app.exception_handler(HTTPException)
    async def _http(_: Request, exc: HTTPException):
        if isinstance(exc.detail, dict):
            return JSONResponse(status_code=exc.status_code, content=exc.detail)
        return JSONResponse(status_code=exc.status_code, content={"error": "http_error", "message": str(exc.detail)})

    @app.exception_handler(SQLAlchemyError)
    async def _db(_: Request, exc: SQLAlchemyError):
        log.exception("database error")
        return JSONResponse(status_code=500, content={"error": "database_error", "message": "A database error occurred."})

    @app.exception_handler(Exception)
    async def _any(_: Request, exc: Exception):
        log.exception("unhandled error")
        return JSONResponse(status_code=500, content={"error": "internal_error", "message": "Internal server error."})

    return app


app = create_app()
