from __future__ import annotations

import re
from datetime import timedelta

import pytest
from aioresponses import aioresponses
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from firm_radar.config import Settings
from firm_radar.identifiers import IdKind, Query
from firm_radar.models import Company
from firm_radar.services.jobs import JobReport, JobRunner
from firm_radar.services.procurement import ProcurementService
from firm_radar.services.profiles import ProfileService
from firm_radar.sources import Sources
from firm_radar.sources.base import today, utcnow
from tests import cassettes

KRS_NO = "0009999901"
NIP = "1234563218"


@pytest.fixture
def profiles(sessionmaker: async_sessionmaker[AsyncSession], sources: Sources) -> ProfileService:
    return ProfileService(sessionmaker, sources)


@pytest.fixture
def runner(
    settings: Settings,
    sessionmaker: async_sessionmaker[AsyncSession],
    sources: Sources,
    profiles: ProfileService,
) -> JobRunner:
    procurement = ProcurementService(sessionmaker, sources.bzp)
    return JobRunner(settings, sessionmaker, sources, profiles, procurement)


async def _track_company(profiles: ProfileService, http: aioresponses) -> int:
    cassettes.krs_extract(http, KRS_NO, "krs_odpis_0009999901_v1.json")
    cassettes.whitelist(http, "nip", NIP, "wl_nip_1234563218.json")
    return (await profiles.resolve(Query(IdKind.KRS, KRS_NO))).company.id


async def test_bulletin_triggers_refresh_bypassing_cache(
    runner: JobRunner, profiles: ProfileService, http: aioresponses
) -> None:
    await _track_company(profiles, http)
    yesterday = today() - timedelta(days=1)
    http.get(
        re.compile(rf".*/api/Krs/Biuletyn/{yesterday.isoformat()}$"),
        payload=cassettes.load("krs_biuletyn.json"),
    )
    # The KRS extract is still cached, but the bulletin says the company changed.
    cassettes.krs_extract(http, KRS_NO, "krs_odpis_0009999901_v2.json")
    report = JobReport()
    await runner.refresh_from_bulletin(yesterday, report)
    assert (report.bulletin_hits, report.refreshed, report.changed) == (1, 1, 1)


async def test_refresh_stale_only_touches_old_profiles(
    runner: JobRunner,
    profiles: ProfileService,
    http: aioresponses,
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    company_id = await _track_company(profiles, http)
    report = JobReport()
    await runner.refresh_stale(report)
    assert report.refreshed == 0

    async with sessionmaker() as session:
        await session.execute(
            update(Company)
            .where(Company.id == company_id)
            .values(last_checked_at=utcnow() - timedelta(days=2))
        )
        await session.commit()
    await runner.refresh_stale(report)
    assert (report.refreshed, report.changed, report.failed) == (1, 0, 0)


async def test_run_locked_full_cycle(
    runner: JobRunner, http: aioresponses, settings: Settings
) -> None:
    http.get(re.compile(r".*/api/Krs/Biuletyn/.*"), payload=[])
    http.get(re.compile(r".*/mo-board/api/v1/notice\?.*"), payload=[], repeat=True)
    report = await runner.run_locked()
    assert report is not None
    assert report.errors == []
    assert report.bzp_days == settings.bzp_ingest_days


async def test_failures_are_reported_not_raised(runner: JobRunner, http: aioresponses) -> None:
    http.get(re.compile(r".*/api/Krs/Biuletyn/.*"), status=500, repeat=True)
    http.get(re.compile(r".*/mo-board/.*"), status=500, repeat=True)
    report = await runner.run_once()
    assert len(report.errors) == 2
