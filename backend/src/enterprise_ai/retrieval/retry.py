"""Bounded async retry policy for transient provider failures."""

import asyncio
from collections.abc import Awaitable, Callable

from enterprise_ai.retrieval.exceptions import RetrievalTransientError


def retry_delay(attempt: int, base_seconds: float, jitter: float = 0.2) -> float:
    deterministic_jitter = (attempt * 0.137) % jitter if jitter else 0.0
    return float(base_seconds * (2**attempt) * (1 + deterministic_jitter))


async def with_retries[ResultT](
    operation: Callable[[], Awaitable[ResultT]],
    *,
    maximum_retries: int,
    base_seconds: float,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> ResultT:
    for attempt in range(maximum_retries + 1):
        try:
            return await operation()
        except asyncio.CancelledError:
            raise
        except RetrievalTransientError:
            if attempt >= maximum_retries:
                raise
            await sleep(retry_delay(attempt, base_seconds))
    raise RuntimeError("unreachable")
