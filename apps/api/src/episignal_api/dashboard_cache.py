"""Bounded, process-local caching for the public dashboard read model."""

import time
from collections import OrderedDict
from collections.abc import Callable
from threading import Lock

from episignal_backend.events.read import DashboardEventPage

DashboardKey = tuple[str | None, str | None, bool]


class DashboardCache:
    """Reuse successful reads for 60 seconds and coalesce concurrent misses.

    Each app owns its cache. Filters and ranking mode have separate entries;
    failures never enter the cache. The fixed capacity bounds arbitrary query
    parameters, and monotonic expiry does not change evidence timestamps.
    """

    def __init__(self) -> None:
        self._entries: OrderedDict[DashboardKey, tuple[float, DashboardEventPage]] = OrderedDict()
        self._lock = Lock()

    def get(self, key: DashboardKey, load: Callable[[], DashboardEventPage]) -> DashboardEventPage:
        with self._lock:
            cached = self._entries.get(key)
            if cached is not None and time.monotonic() < cached[0]:
                self._entries.move_to_end(key)
                return cached[1]

            page = load()
            self._entries[key] = (time.monotonic() + 60, page)
            self._entries.move_to_end(key)
            while len(self._entries) > 32:
                self._entries.popitem(last=False)
            return page
