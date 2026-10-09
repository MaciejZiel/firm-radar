"""PostgreSQL implementation of :class:`SourceStore`."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, select
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

    async def cache_invalidate(self, source: SourceName, key_pattern: str) -> int:
        """Drop cached responses whose key matches a SQL LIKE pattern."""
        async with self._sessionmaker() as session:
            result = await session.execute(
                delete(SourceCache).where(
                    SourceCache.source == source.value, SourceCache.key.like(key_pattern)
                )
            )
            await session.commit()
        return int(getattr(result, "rowcount", 0) or 0)

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
            day=today(),
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

    async def status_today(self) -> dict[str, SourceStatus]:
        async with self._sessionmaker() as session:
            rows = await session.scalars(select(SourceStatus).where(SourceStatus.day == today()))
            return {row.source: row for row in rows}

    async def last_seen(self) -> dict[str, tuple[datetime | None, datetime | None, str | None]]:
        """Most recent success/failure per source over all days."""
        async with self._sessionmaker() as session:
            rows = await session.execute(
                select(
                    SourceStatus.source,
                    func.max(SourceStatus.last_ok_at),
                    func.max(SourceStatus.last_error_at),
                ).group_by(SourceStatus.source)
            )
            result: dict[str, tuple[datetime | None, datetime | None, str | None]] = {}
            for source, last_ok, last_error_at in rows:
                message = None
                if last_error_at is not None:
                    message = await session.scalar(
                        select(SourceStatus.last_error).where(
                            SourceStatus.source == source,
                            SourceStatus.last_error_at == last_error_at,
                        )
                    )
                result[source] = (last_ok, last_error_at, message)
            return result

    async def cache_entries(self) -> dict[str, int]:
        async with self._sessionmaker() as session:
            rows = await session.execute(
                select(SourceCache.source, func.count())
                .where(SourceCache.expires_at > utcnow())
                .group_by(SourceCache.source)
            )
            return {source: int(count) for source, count in rows}
