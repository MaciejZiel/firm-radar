"""Assemble the sources/health report."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from firm_radar.api.models import BzpCoverageOut, HealthOut, SourceHealthOut
from firm_radar.config import Settings
from firm_radar.models import BzpIngestDay
from firm_radar.sources.base import SourceName
from firm_radar.sources.catalog import CATALOG
from firm_radar.sources.store import PgSourceStore

Status = Literal["ok", "degraded", "down", "unknown"]


def _status(last_ok: datetime | None, last_error: datetime | None, errors_today: int) -> Status:
    if last_ok is None and last_error is None:
        return "unknown"
    if last_error is not None and (last_ok is None or last_error > last_ok):
        return "down"
    return "degraded" if errors_today else "ok"


async def build_health(
    settings: Settings, store: PgSourceStore, sessionmaker: async_sessionmaker[AsyncSession]
) -> HealthOut:
    today = await store.status_today()
    seen = await store.last_seen()
    cached = await store.cache_entries()
    sources = []
    for name, info in CATALOG.items():
        row = today.get(name.value)
        last_ok, last_error_at, last_error = seen.get(name.value, (None, None, None))
        requests = row.requests if row else 0
        errors = row.errors if row else 0
        budget = settings.whitelist_daily_budget if name is SourceName.WHITELIST else None
        sources.append(
            SourceHealthOut(
                source=name.value,
                label=info.label,
                status=_status(last_ok, last_error_at, errors),
                docs_url=info.docs_url,
                terms=info.terms,
                limits=info.limits,
                requests_today=requests,
                errors_today=errors,
                last_ok_at=last_ok,
                last_error_at=last_error_at,
                last_error=last_error,
                cached_responses=cached.get(name.value, 0),
                daily_budget=budget,
                budget_left=max(budget - requests, 0) if budget is not None else None,
            )
        )
    async with sessionmaker() as session:
        days, first, last, awards = (
            await session.execute(
                select(
                    func.count(BzpIngestDay.day),
                    func.min(BzpIngestDay.day),
                    func.max(BzpIngestDay.day),
                    func.coalesce(func.sum(BzpIngestDay.awards), 0),
                )
            )
        ).one()
    return HealthOut(
        sources=sources,
        bzp_coverage=BzpCoverageOut(days=days, first_day=first, last_day=last, awards=awards),
        scheduler_enabled=settings.scheduler_enabled,
    )
