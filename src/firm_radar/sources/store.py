"""PostgreSQL implementation of :class:`SourceStore`."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from firm_radar.models import SourceCache, SourceStatus
from firm_radar.sources.base import CachedResponse, SourceName, today, utcnow


class PgSourceStore:
    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self._sessionmaker = sessionmaker

    async def cache_get(self, source: SourceName, key: str) -> CachedResponse | None:
        async with self._sessionmaker() as session:
            row = await session.scalar(
                select(SourceCache).where(
                    SourceCache.source == source.value,
                    SourceCache.key == key,
                    SourceCache.expires_at > utcnow(),
                )
            )
        if row is None:
            return None
        return CachedResponse(row.status, row.payload, row.fetched_at, from_cache=True)

    async def cache_put(
        self, source: SourceName, key: str, status: int, payload: Any, ttl: timedelta
    ) -> datetime:
        now = utcnow()
        values = {
            "source": source.value,
            "key": key,
            "status": status,
            "payload": payload,
            "fetched_at": now,
            "expires_at": now + ttl,
        }
        stmt = insert(SourceCache).values(**values)
        stmt = stmt.on_conflict_do_update(
            constraint="uq_source_cache_source_key",
            set_={k: stmt.excluded[k] for k in ("status", "payload", "fetched_at", "expires_at")},
        )
        async with self._sessionmaker() as session:
            await session.execute(stmt)
            await session.commit()
        return now

    async def purge_expired(self) -> int:
        async with self._sessionmaker() as session:
            result = await session.execute(
                delete(SourceCache).where(SourceCache.expires_at <= utcnow())
            )
            await session.commit()
        return int(getattr(result, "rowcount", 0) or 0)

    async def requests_today(self, source: SourceName) -> int:
        async with self._sessionmaker() as session:
            value = await session.scalar(
                select(SourceStatus.requests).where(
                    SourceStatus.source == source.value, SourceStatus.day == today()
                )
            )
        return int(value or 0)

    async def record(self, source: SourceName, *, ok: bool, error: str | None = None) -> None:
        now = utcnow()
        stmt = insert(SourceStatus).values(
            source=source.value,
            day=now.date(),
            requests=1,
            errors=0 if ok else 1,
            last_ok_at=now if ok else None,
            last_error_at=None if ok else now,
            last_error=None if ok else (error or "unknown error")[:500],
        )
        update: dict[str, Any] = {"requests": SourceStatus.requests + 1}
        if ok:
            update["last_ok_at"] = now
        else:
            update.update(
                errors=SourceStatus.errors + 1,
                last_error_at=now,
                last_error=stmt.excluded.last_error,
            )
        stmt = stmt.on_conflict_do_update(constraint="uq_source_status_source_day", set_=update)
        async with self._sessionmaker() as session:
            await session.execute(stmt)
            await session.commit()
