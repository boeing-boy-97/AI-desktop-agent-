"""Real-time event bus + SSE publishing for live UI updates."""
from __future__ import annotations

import asyncio
import itertools
import threading
from collections.abc import Callable
from dataclasses import dataclass, field

from core.utils import iso_now


@dataclass
class AgentEvent:
    event: str
    data: dict = field(default_factory=dict)
    timestamp: str = field(default_factory=iso_now)

    def as_dict(self) -> dict:
        return {"event": self.event, "data": self.data, "timestamp": self.timestamp}


class EventBus:
    """In-process pub/sub with an ordered history ring and async fan-out.

    Subscribers can be synchronous callbacks or asyncio queues (used by the
    FastAPI SSE endpoint to stream events to the desktop UI in real time).
    """

    def __init__(self, history_size: int = 500) -> None:
        self._subs: dict[int, Callable] = {}
        self._queues: dict[int, asyncio.Queue] = {}
        self._history: list[AgentEvent] = []
        self._history_size = history_size
        self._counters = itertools.count(1)
        self._lock = threading.Lock()

    def subscribe(self, callback: Callable[[AgentEvent], None]) -> int:
        with self._lock:
            sid = next(self._counters)
            self._subs[sid] = callback
            return sid

    def unsubscribe(self, sid: int) -> None:
        with self._lock:
            self._subs.pop(sid, None)

    def publisher(self, queue: asyncio.Queue) -> int:
        """Register an asyncio queue that will receive every new event."""
        with self._lock:
            sid = next(self._counters)
            self._queues[sid] = queue
            return sid

    def unpublish(self, sid: int) -> None:
        with self._lock:
            self._queues.pop(sid, None)

    def emit(self, event: str, data: dict | None = None) -> None:
        evt = AgentEvent(event=event, data=data or {})
        with self._lock:
            self._history.append(evt)
            if len(self._history) > self._history_size:
                self._history = self._history[-self._history_size:]
            subs = list(self._subs.items())
            queues = list(self._queues.items())
        for _, cb in subs:
            try:
                cb(evt)
            except Exception:
                pass
        for _, q in queues:
            try:
                q.put_nowait(evt)
            except asyncio.QueueFull:
                pass

    def history(self, limit: int = 100) -> list[AgentEvent]:
        with self._lock:
            return list(self._history[-limit:])

    def clear_history(self) -> None:
        with self._lock:
            self._history.clear()


# Convenience constructors for common events
def evt_listening(data: dict | None = None) -> AgentEvent:
    e = AgentEvent("agent.listening", data or {})
    return e


def evt_emit(bus: EventBus, event: str, **data) -> None:
    bus.emit(event, data)
