"""Shared HTTP plumbing for upstream registries: retries, timeouts, TTL cache, health counters."""

from __future__ import annotations

import asyncio
import logging
import random
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from enum import StrEnum
from typing import Any, Protocol
from zoneinfo import ZoneInfo

import aiohttp

from firm_radar.config import Settings

log = logging.getLogger(__name__)

RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})


class SourceName(StrEnum):
    KRS = "krs"
    WHITELIST = "whitelist"
    BZP = "bzp"


class SourceError(Exception):
    """An upstream registry could not answer."""

    def __init__(self, source: SourceName, message: str) -> None:
        super().__init__(f"{source}: {message}")
        self.source = source
        self.message = message


class SourceUnavailable(SourceError):
    """Network failure, timeout or 5xx after all retries."""


class QuotaExceeded(SourceError):
    """We are about to exceed the daily request budget agreed for a source."""


class BadRequest(SourceError):
    """The registry rejected the query (e.g. invalid identifier)."""


@dataclass(frozen=True, slots=True)
class CachedResponse:
    status: int
    payload: Any
    fetched_at: datetime
    from_cache: bool


class SourceStore(Protocol):
    """Persistence used by clients: response cache plus per-day health counters."""

    async def cache_get(self, source: SourceName, key: str) -> CachedResponse | None: ...

    async def cache_put(
        self, source: SourceName, key: str, status: int, payload: Any, ttl: timedelta
    ) -> datetime: ...

    async def requests_today(self, source: SourceName) -> int: ...

    async def record(self, source: SourceName, *, ok: bool, error: str | None = None) -> None: ...


@dataclass(frozen=True, slots=True)
class HttpResult:
    status: int
    payload: Any
    url: str


class HttpFetcher:
    """GET JSON with bounded retries and exponential backoff with jitter."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        settings: Settings,
        store: SourceStore,
    ) -> None:
        self._session = session
        self._timeout = aiohttp.ClientTimeout(total=settings.http_timeout_s)
        self._retries = max(1, settings.http_retries)
        self._backoff = settings.http_backoff_s
        self._headers = {"User-Agent": settings.user_agent, "Accept": "application/json"}
        self.store = store

    async def get_json(
        self, source: SourceName, url: str, params: dict[str, str] | None = None
    ) -> HttpResult:
        last_error = "no attempt made"
        for attempt in range(1, self._retries + 1):
            try:
                async with self._session.get(
                    url, params=params, headers=self._headers, timeout=self._timeout
                ) as resp:
                    if resp.status in RETRY_STATUSES:
                        last_error = f"HTTP {resp.status}"
                        retry_after = _retry_after(resp.headers.get("Retry-After"))
                        if attempt < self._retries:
                            await asyncio.sleep(retry_after or self._delay(attempt))
                            continue
                        break
                    payload = await _read_json(resp)
                    await self.store.record(source, ok=resp.status < 500)
                    return HttpResult(resp.status, payload, str(resp.url))
            except (aiohttp.ClientError, TimeoutError) as exc:
                last_error = f"{type(exc).__name__}: {exc}".strip(": ")
                log.warning("%s attempt %d/%d failed: %s", source, attempt, self._retries, exc)
                if attempt < self._retries:
                    await asyncio.sleep(self._delay(attempt))
        await self.store.record(source, ok=False, error=last_error)
        raise SourceUnavailable(source, last_error)

    def _delay(self, attempt: int) -> float:
        base: float = self._backoff * 2 ** (attempt - 1)
        return base + random.uniform(0, base / 2)  # noqa: S311 - jitter, not crypto


async def _read_json(resp: aiohttp.ClientResponse) -> Any:
    raw = await resp.read()
    if not raw.strip():
        return None
    try:
        return await resp.json(content_type=None)
    except ValueError:
        # Some gateways answer with HTML error pages; treat the body as opaque.
        return None


def _retry_after(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return min(float(value), 30.0)
    except ValueError:
        return None


def utcnow() -> datetime:
    return datetime.now(UTC)


WARSAW = ZoneInfo("Europe/Warsaw")


def today() -> date:
    """Calendar day in Poland; registries and their daily quotas follow local time."""
    return utcnow().astimezone(WARSAW).date()
