"""Bounded, process-local caching for the public dashboard read model."""

import asyncio
import time
from collections import OrderedDict
from collections.abc import Callable
from concurrent.futures import Future
from threading import Lock

from episignal_backend.events.read import DashboardEventPage
from starlette.concurrency import run_in_threadpool

DashboardKey = tuple[str | None, str | None, bool]


class DashboardCache:
    """Reuse successful reads for 60 seconds and coalesce concurrent misses.

    Each app owns its cache. Filters and ranking mode have separate entries;
    failures never enter the cache. The fixed capacity bounds arbitrary query
    parameters, and monotonic expiry does not change evidence timestamps.
    """

    def __init__(self) -> None:
        self._entries: OrderedDict[DashboardKey, tuple[float, DashboardEventPage]] = OrderedDict()
        self._pending: dict[DashboardKey, Future[DashboardEventPage]] = {}
        self._lock = Lock()

    async def get(
        self, key: DashboardKey, load: Callable[[], DashboardEventPage]
    ) -> DashboardEventPage:
        with self._lock:
            cached = self._entries.get(key)
            if cached is not None and time.monotonic() < cached[0]:
                self._entries.move_to_end(key)
                return cached[1]

            pending = self._pending.get(key)
            owns_load = pending is None
            if pending is None:
                pending = Future()
                self._pending[key] = pending

        if owns_load:
            await run_in_threadpool(self._load, key, pending, load)

        # Cancellation of one HTTP request must not cancel the shared result.
        return await asyncio.shield(asyncio.wrap_future(pending))

    def _load(
        self,
        key: DashboardKey,
        pending: Future[DashboardEventPage],
        load: Callable[[], DashboardEventPage],
    ) -> None:
        try:
            page = load()
        except BaseException as error:
            with self._lock:
                pending.set_exception(error)
                del self._pending[key]
            return

        with self._lock:
            self._entries[key] = (time.monotonic() + 60, page)
            self._entries.move_to_end(key)
            while len(self._entries) > 32:
                self._entries.popitem(last=False)
            pending.set_result(page)
            del self._pending[key]
