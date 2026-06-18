from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar

import httpx

T = TypeVar("T")

RETRYABLE_STATUS_CODES = {408, 409, 425, 429, 500, 502, 503, 504}


async def retry_async(
    operation: Callable[[], Awaitable[T]],
    *,
    attempts: int,
    retry_exceptions: tuple[type[BaseException], ...],
    should_retry_result: Callable[[T], bool] | None = None,
    delay_seconds: float = 0.2,
    backoff_factor: float = 2.0,
) -> T:
    max_attempts = max(1, attempts)
    delay = max(0.0, delay_seconds)
    for attempt in range(1, max_attempts + 1):
        try:
            result = await operation()
        except retry_exceptions:
            if attempt >= max_attempts:
                raise
        else:
            if should_retry_result is None or not should_retry_result(result):
                return result
            if attempt >= max_attempts:
                return result

        if delay > 0:
            await asyncio.sleep(delay)
        delay *= max(1.0, backoff_factor)

    raise RuntimeError("retry_async exhausted without returning a result.")


def should_retry_http_response(response: httpx.Response) -> bool:
    return response.status_code in RETRYABLE_STATUS_CODES
