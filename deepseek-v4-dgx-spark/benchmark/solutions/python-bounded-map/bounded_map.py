"""Ordered asynchronous mapping with bounded concurrency and cleanup."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterable
from typing import TypeVar


T = TypeVar("T")
R = TypeVar("R")
_MISSING = object()


async def bounded_map(
    function: Callable[[T], Awaitable[R]],
    items: Iterable[T],
    *,
    limit: int,
) -> list[R]:
    """Apply ``function`` with at most ``limit`` active calls at a time.

    On a worker error or caller cancellation, all outstanding workers are
    cancelled and awaited before the original exception is re-raised.
    """
    if isinstance(limit, bool) or not isinstance(limit, int):
        raise TypeError("limit must be an integer")
    if limit <= 0:
        raise ValueError("limit must be positive")

    iterator = iter(items)
    active: dict[asyncio.Future[R], int] = {}
    results: list[R | object] = []

    def start_one() -> bool:
        try:
            item = next(iterator)
        except StopIteration:
            return False
        index = len(results)
        results.append(_MISSING)
        future = asyncio.ensure_future(function(item))
        active[future] = index
        return True

    async def cancel_and_collect() -> None:
        for future in active:
            if not future.done():
                future.cancel()
        if active:
            await asyncio.gather(*active, return_exceptions=True)

    try:
        for _ in range(limit):
            if not start_one():
                break

        while active:
            done, _ = await asyncio.wait(active, return_when=asyncio.FIRST_COMPLETED)
            for future in sorted(done, key=lambda item: active[item]):
                index = active.pop(future)
                results[index] = future.result()
                start_one()
    except BaseException:
        await cancel_and_collect()
        raise

    return [value for value in results]  # type: ignore[return-value]
