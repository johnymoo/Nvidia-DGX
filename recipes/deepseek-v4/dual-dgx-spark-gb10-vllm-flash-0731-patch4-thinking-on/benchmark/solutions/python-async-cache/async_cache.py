"""Async TTL cache with per-key single-flight loading."""

from __future__ import annotations

import asyncio
import math
import time
from collections.abc import Awaitable, Callable, Hashable
from typing import Generic, TypeVar


K = TypeVar("K", bound=Hashable)
V = TypeVar("V")


class AsyncTTLCache(Generic[K, V]):
    def __init__(self, ttl_seconds: float, *, clock: Callable[[], float] = time.monotonic):
        if isinstance(ttl_seconds, bool) or not isinstance(ttl_seconds, (int, float)):
            raise TypeError("ttl_seconds must be a number")
        if not math.isfinite(ttl_seconds) or ttl_seconds < 0:
            raise ValueError("ttl_seconds must be finite and non-negative")
        if not callable(clock):
            raise TypeError("clock must be callable")
        self._ttl_seconds = float(ttl_seconds)
        self._clock = clock
        self._entries: dict[K, tuple[float, V]] = {}
        self._inflight: dict[K, asyncio.Future[V]] = {}

    async def get_or_load(self, key: K, loader: Callable[[], Awaitable[V]]) -> V:
        entry = self._entries.get(key)
        if entry is not None:
            expires_at, value = entry
            if self._clock() < expires_at:
                return value
            self._entries.pop(key, None)

        task = self._inflight.get(key)
        if task is None:
            async def load_and_store() -> V:
                try:
                    value = await loader()
                    self._entries[key] = (self._clock() + self._ttl_seconds, value)
                    return value
                finally:
                    self._inflight.pop(key, None)

            task = asyncio.create_task(load_and_store())
            self._inflight[key] = task

        # A cancelled waiter must not cancel the shared loader for other callers.
        return await asyncio.shield(task)

    def invalidate(self, key: K) -> None:
        self._entries.pop(key, None)

    def clear(self) -> None:
        self._entries.clear()
