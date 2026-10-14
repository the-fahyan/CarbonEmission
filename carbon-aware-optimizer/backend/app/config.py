"""Application configuration, read from environment variables (see .env.example)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent


def _load_dotenv() -> None:
    """Tiny .env loader so we do not need an extra dependency."""
    for candidate in (BACKEND_DIR / ".env", BACKEND_DIR.parent / ".env"):
        if candidate.exists():
            for line in candidate.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    os.environ.setdefault(key.strip(), value.strip())


_load_dotenv()


@dataclass(frozen=True)
class Config:
    database_url: str
    frontend_origins: list[str]
    worker_tick_seconds: float
    event_buffer_size: int
    log_retention_rows: int


def load_config() -> Config:
    default_db = BACKEND_DIR / "data" / "carbon_optimizer.db"
    frontend_origins = [
        o.strip()
        for o in os.getenv(
            "FRONTEND_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
        ).split(",")
        if o.strip()
    ]
    return Config(
        database_url=os.getenv("DATABASE_URL", f"sqlite:///{default_db.as_posix()}"),
        frontend_origins=[
            origin if "://" in origin else f"https://{origin}"
            for origin in frontend_origins
        ],
        worker_tick_seconds=float(os.getenv("WORKER_TICK_SECONDS", "0.5")),
        event_buffer_size=int(os.getenv("EVENT_BUFFER_SIZE", "500")),
        log_retention_rows=int(os.getenv("LOG_RETENTION_ROWS", "20000")),
    )
