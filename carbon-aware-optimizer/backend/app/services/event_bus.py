"""In-process pub/sub used by the SSE endpoint.

* `publish` is thread-safe (API handlers run in a threadpool, the worker in the event loop).
* A bounded ring buffer keeps recent events so a reconnecting client can resume via Last-Event-ID.
"""
from __future__ import annotations

import asyncio
import json
import threading
from collections import deque
from typing import Any

from app.utils.timeutil import utcnow


class EventBus:
    def __init__(self, buffer_size: int = 500) -> None:
        self._buffer: deque[dict[str, Any]] = deque(maxlen=buffer_size)
        self._subscribers: set[asyncio.Queue] = set()
        self._lock = threading.Lock()
        self._next_id = 1
        self._loop: asyncio.AbstractEventLoop | None = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def publish(self, event_type: str, data: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            evt = {"id": self._next_id, "type": event_type, "data": data,
                   "ts": utcnow().isoformat() + "Z"}
            self._next_id += 1
            self._buffer.append(evt)
            subs = list(self._subscribers)
        for q in subs:
            self._deliver(q, evt)
        return evt

    def _deliver(self, q: asyncio.Queue, evt: dict[str, Any]) -> None:
        def put() -> None:
            try:
                q.put_nowait(evt)
            except asyncio.QueueFull:  # slow client: drop oldest, keep newest
                try:
                    q.get_nowait()
                    q.put_nowait(evt)
                except Exception:  # noqa: BLE001
                    pass

        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(put)
        else:
            put()

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=200)
        with self._lock:
            self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        with self._lock:
            self._subscribers.discard(q)

    def recent(self, after_id: int = 0, limit: int = 100) -> list[dict[str, Any]]:
        with self._lock:
            items = [e for e in self._buffer if e["id"] > after_id]
        return items[-limit:]

    @staticmethod
    def format_sse(evt: dict[str, Any]) -> str:
        return f"id: {evt['id']}\nevent: {evt['type']}\ndata: {json.dumps(evt)}\n\n"
