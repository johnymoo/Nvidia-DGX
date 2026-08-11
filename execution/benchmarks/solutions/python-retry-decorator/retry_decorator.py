"""A retry decorator that preserves sync and async call styles."""

from __future__ import annotations

import asyncio
import functools
import inspect
import math
import time
from collections.abc import Callable
from typing import Any


def _number(name: str, value: float, *, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be a number")
    if not math.isfinite(value) or value < 0 or (positive and value == 0):
        qualifier = "positive" if positive else "non-negative"
        raise ValueError(f"{name} must be finite and {qualifier}")
    return float(value)


def retry(
    *,
    attempts: int,
    exceptions: tuple[type[BaseException], ...] = (Exception,),
    sleep: Callable[[float], Any] | None = None,
    delay: float = 0,
    backoff: float = 1,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Retry a callable up to ``attempts`` total invocations.

    For async callables, an injected sleeper may be synchronous or awaitable.
    For synchronous callables it must be synchronous.
    """
    if isinstance(attempts, bool) or not isinstance(attempts, int):
        raise TypeError("attempts must be an integer")
    if attempts <= 0:
        raise ValueError("attempts must be positive")
    delay = _number("delay", delay)
    backoff = _number("backoff", backoff)
    if not isinstance(exceptions, tuple) or not exceptions:
        raise TypeError("exceptions must be a non-empty tuple")
    if not all(isinstance(item, type) and issubclass(item, BaseException) for item in exceptions):
        raise TypeError("exceptions must contain exception classes")
    if sleep is not None and not callable(sleep):
        raise TypeError("sleep must be callable")

    def decorate(function: Callable[..., Any]) -> Callable[..., Any]:
        if inspect.iscoroutinefunction(function):
            async def async_wrapped(*args: Any, **kwargs: Any) -> Any:
                sleeper = sleep or asyncio.sleep
                for call_number in range(attempts):
                    try:
                        return await function(*args, **kwargs)
                    except exceptions:
                        if call_number + 1 == attempts:
                            raise
                        outcome = sleeper(delay * (backoff ** call_number))
                        if inspect.isawaitable(outcome):
                            await outcome

            return functools.wraps(function)(async_wrapped)  # type: ignore[return-value]

        @functools.wraps(function)
        def sync_wrapped(*args: Any, **kwargs: Any) -> Any:
            sleeper = sleep or time.sleep
            for call_number in range(attempts):
                try:
                    return function(*args, **kwargs)
                except exceptions:
                    if call_number + 1 == attempts:
                        raise
                    outcome = sleeper(delay * (backoff ** call_number))
                    if inspect.isawaitable(outcome):
                        if inspect.iscoroutine(outcome):
                            outcome.close()
                        raise TypeError("sync retry sleeper must not return an awaitable")

        return sync_wrapped  # type: ignore[return-value]

    return decorate
