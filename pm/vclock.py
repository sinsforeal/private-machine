"""Injectable clock for a harness that drives the companion in virtual time.

Leaf module: it imports only the standard library. Without ``install`` every
function returns real time, so normal runs are unchanged. With ``install`` the
whole process reads one virtual clock that only moves when the harness calls
``VirtualClock.set``. The virtual clock holds local wall time (the harness
chooses the zone), because the prompts print naive datetimes.

``busy`` counts units of work in flight (a module batch, a model call). The
harness waits for ``busy == 0`` to know the system is quiet before it moves
time on.
"""
from __future__ import annotations

import threading
import time as _time
from datetime import datetime, timedelta, timezone

#: Real seconds a module blocks per mailbox wait in stepped mode.
POLL_CAP_SECONDS = 0.02


class VirtualClock:
    """A settable clock. ``start`` is a naive datetime in the harness zone."""

    def __init__(self, start: datetime, utc_offset_hours: float = 0.0) -> None:
        self._lock = threading.Lock()
        self._start = start
        self._now = start
        self.utc_offset = timedelta(hours=utc_offset_hours)

    def now(self) -> datetime:
        with self._lock:
            return self._now

    def set(self, value: datetime) -> None:
        with self._lock:
            self._now = value

    def monotonic(self) -> float:
        with self._lock:
            return (self._now - self._start).total_seconds()


_active: VirtualClock | None = None
_busy = 0
_busy_lock = threading.Lock()


def install(clock: VirtualClock | None) -> None:
    """Make ``clock`` the process clock; ``None`` restores real time."""
    global _active
    _active = clock


def active() -> VirtualClock | None:
    return _active


def utcnow() -> datetime:
    """Naive datetime, like ``datetime.utcnow()``."""
    clock = _active
    return clock.now() if clock is not None else datetime.utcnow()


def now_aware() -> datetime:
    """Timezone-aware datetime, like ``datetime.now(timezone.utc)``."""
    clock = _active
    if clock is None:
        return datetime.now(timezone.utc)
    return (clock.now() - clock.utc_offset).replace(tzinfo=timezone.utc)


def monotonic() -> float:
    clock = _active
    return clock.monotonic() if clock is not None else _time.monotonic()


def stepped() -> bool:
    return _active is not None


def wait_cap(wait: float | None) -> float | None:
    """Cap a mailbox wait in stepped mode so threads re-read the clock."""
    if _active is None:
        return wait
    return POLL_CAP_SECONDS if wait is None else min(wait, POLL_CAP_SECONDS)


class busy:
    """Context manager that counts work in flight."""

    def __enter__(self):
        global _busy
        with _busy_lock:
            _busy += 1
        return self

    def __exit__(self, *_exc):
        global _busy
        with _busy_lock:
            _busy -= 1
        return False


#: Optional hook ``(call_id, route, virtual_now)`` the harness sets to link
#: model calls to outputs. Called for every finished model request.
call_hook = None


def note_call(call_id, route) -> None:
    hook = call_hook
    if hook is not None and call_id:
        hook(call_id, route, utcnow())


def busy_count() -> int:
    return _busy
