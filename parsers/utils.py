import asyncio
import logging
import random
from typing import Any, Awaitable, Callable

logger = logging.getLogger(__name__)


async def _release_response(response: Any) -> None:
    """Helper to safely close or release HTTP response connections."""
    if response is None:
        return
    try:
        if hasattr(response, "release"):
            res = response.release()
            if asyncio.iscoroutine(res):
                await res
        elif hasattr(response, "close"):
            res = response.close()
            if asyncio.iscoroutine(res):
                await res
    except Exception:
        pass


async def fetch_with_retry(
    request_func: Callable[[], Awaitable[Any]],
    max_retries: int = 3,
    backoff_factor: float = 1.5,
    retry_statuses: tuple[int, ...] = (429, 500, 502, 503, 504),
) -> Any:
    """Performs an async HTTP request with exponential backoff, jitter, and connection pool safety.

    Args:
        request_func: A zero-argument async function returning a response object.
        max_retries: Maximum number of retry attempts.
        backoff_factor: Base multiplier for exponential backoff.
        retry_statuses: HTTP status codes that trigger a retry.

    Returns:
        The response object.
    """
    for attempt in range(1, max_retries + 1):
        response = None
        try:
            response = await request_func()
            status = getattr(response, "status", None) or getattr(response, "status_code", None)

            if status in retry_statuses:
                if attempt == max_retries:
                    logger.warning(f"[Network] Reached max retries ({max_retries}) for status {status}.")
                    return response

                # Safely release connection back to pool before sleeping
                await _release_response(response)

                jitter = random.uniform(0.1, 0.7)
                sleep_time = (backoff_factor ** attempt) + jitter
                logger.warning(
                    f"[Network] Received status {status}. Retrying attempt {attempt}/{max_retries} in {sleep_time:.2f}s..."
                )
                await asyncio.sleep(sleep_time)
                continue

            if status in (403, 404):
                logger.warning(f"[Network] Received non-retryable status {status}.")
                return response

            return response

        except (asyncio.TimeoutError, Exception) as exc:
            if response is not None:
                await _release_response(response)

            if attempt == max_retries:
                logger.error(f"[Network] Max retries reached after exception: {exc}")
                raise exc

            jitter = random.uniform(0.1, 0.7)
            sleep_time = (backoff_factor ** attempt) + jitter
            logger.warning(
                f"[Network] Exception encountered: {exc}. Retrying attempt {attempt}/{max_retries} in {sleep_time:.2f}s..."
            )
            await asyncio.sleep(sleep_time)
