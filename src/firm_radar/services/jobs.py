"""Background refresh jobs: stale profiles, KRS change bulletin, BZP ingest, cache purge."""

from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import date, timedelta

from sqlalchemy import or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from firm_radar.config import Settings
from firm_radar.models import Company
from firm_radar.services.procurement import ProcurementService
from firm_radar.services.profiles import ProfileService
from firm_radar.sources import Sources
from firm_radar.sources.base import SourceError, today, utcnow
from firm_radar.sources.store import PgSourceStore

log = logging.getLogger(__name__)

# Arbitrary constant: one advisory lock id for "the job runner" across all app instances.
JOBS_LOCK_ID = 0x46524144  # "FRAD"


@dataclass
class JobReport:
    refreshed: int = 0
    changed: int = 0
    failed: int = 0
    bulletin_hits: int = 0
    bzp_days: int = 0
    cache_purged: int = 0
    errors: list[str] = field(default_factory=list)


class JobRunner:
    def __init__(
        self,
        settings: Settings,
        sessionmaker: async_sessionmaker[AsyncSession],
        sources: Sources,
        profiles: ProfileService,
        procurement: ProcurementService,
    ) -> None:
        self._settings = settings
        self._sessionmaker = sessionmaker
        self._sources = sources
        self._profiles = profiles
        self._procurement = procurement

    async def _refresh(self, company_ids: list[int], report: JobReport) -> None:
        for company_id in company_ids:
            try:
                result = await self._profiles.refresh(company_id)
            except Exception as exc:  # one bad company must not stop the batch
                report.failed += 1
                report.errors.append(f"company {company_id}: {exc}")
                log.warning("refresh of company %s failed: %s", company_id, exc)
                continue
            report.refreshed += 1
            report.changed += int(result.created)

    async def refresh_stale(self, report: JobReport) -> None:
        cutoff = utcnow() - timedelta(seconds=self._settings.snapshot_max_age_s)
        async with self._sessionmaker() as session:
            ids = list(
                await session.scalars(
                    select(Company.id)
                    .where(Company.tracked.is_(True))
                    .where(or_(Company.last_checked_at.is_(None), Company.last_checked_at < cutoff))
                    .order_by(Company.last_checked_at.asc().nulls_first())
                    .limit(self._settings.refresh_batch_size)
                )
            )
        await self._refresh(ids, report)

    async def refresh_from_bulletin(self, day: date, report: JobReport) -> None:
        """Re-read tracked companies that had a KRS entry on ``day``, bypassing the cache."""
        try:
            changed = set(await self._sources.krs.daily_bulletin(day))
        except SourceError as exc:
            report.errors.append(str(exc))
            return
        if not changed:
            return
        async with self._sessionmaker() as session:
            hits = list(
                await session.execute(
                    select(Company.id, Company.krs).where(
                        Company.tracked.is_(True), Company.krs.in_(changed)
                    )
                )
            )
        report.bulletin_hits += len(hits)
        store = self._sources.store
        if isinstance(store, PgSourceStore):
            for _, krs in hits:
                await store.cache_invalidate(self._sources.krs.source, f"OdpisAktualny/%/{krs}")
        await self._refresh([company_id for company_id, _ in hits], report)

    async def run_once(self) -> JobReport:
        report = JobReport()
        await self.refresh_from_bulletin(today() - timedelta(days=1), report)
        await self.refresh_stale(report)
        try:
            results = await self._procurement.ingest_recent(self._settings.bzp_ingest_days)
            report.bzp_days = sum(1 for r in results if not r.skipped)
        except SourceError as exc:
            report.errors.append(str(exc))
        store = self._sources.store
        if isinstance(store, PgSourceStore):
            report.cache_purged = await store.purge_expired()
        log.info("jobs finished: %s", report)
        return report

    async def run_locked(self) -> JobReport | None:
        """Run once unless another instance holds the job lock."""
        async with self._sessionmaker() as session:
            got = await session.scalar(
                text("SELECT pg_try_advisory_lock(:id)"), {"id": JOBS_LOCK_ID}
            )
            if not got:
                log.info("another instance is running jobs; skipping")
                return None
            try:
                return await self.run_once()
            finally:
                await session.execute(text("SELECT pg_advisory_unlock(:id)"), {"id": JOBS_LOCK_ID})


class Scheduler:
    """Runs :class:`JobRunner` periodically inside the web process (good enough for one dyno)."""

    def __init__(self, runner: JobRunner, interval_s: int, initial_delay_s: float = 10.0) -> None:
        self._runner = runner
        self._interval = interval_s
        self._initial_delay = initial_delay_s
        self._task: asyncio.Task[None] | None = None
        self.last_report: JobReport | None = None

    def start(self) -> None:
        self._task = asyncio.create_task(self._loop(), name="firm-radar-jobs")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task

    async def _loop(self) -> None:
        await asyncio.sleep(self._initial_delay)
        while True:
            try:
                self.last_report = await self._runner.run_locked() or self.last_report
            except Exception:
                log.exception("background jobs crashed; retrying next cycle")
            await asyncio.sleep(self._interval)
