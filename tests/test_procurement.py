from __future__ import annotations

from datetime import date

import pytest
from aioresponses import aioresponses
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from firm_radar.services.procurement import ProcurementService
from firm_radar.sources import Sources
from tests import cassettes

NIP = "1234563218"
DAY = date(2026, 10, 1)


@pytest.fixture
def procurement(
    sessionmaker: async_sessionmaker[AsyncSession], sources: Sources
) -> ProcurementService:
    return ProcurementService(sessionmaker, sources.bzp)


async def test_ingest_day_and_summary(procurement: ProcurementService, http: aioresponses) -> None:
    cassettes.bzp_notices(http, "bzp_notices_2026-10-01.json")
    result = await procurement.ingest_day(DAY)
    assert (result.notices, result.awards, result.skipped) == (4, 2, False)

    summary = await procurement.summary(NIP)
    assert (summary.total_awards, summary.total_lots) == (2, 3)
    assert (summary.coverage_from, summary.coverage_to, summary.coverage_days) == (DAY, DAY, 1)
    assert [a.bzp_number for a in summary.recent] == ["2026/BZP 00000002", "2026/BZP 00000001"]


async def test_ingest_is_idempotent(procurement: ProcurementService, http: aioresponses) -> None:
    cassettes.bzp_notices(http, "bzp_notices_2026-10-01.json")
    await procurement.ingest_day(DAY)
    again = await procurement.ingest_day(DAY)  # no HTTP response registered for a second call
    assert again.skipped

    cassettes.bzp_notices(http, "bzp_notices_2026-10-01.json")
    forced = await procurement.ingest_day(DAY, force=True)
    assert not forced.skipped
    assert (await procurement.summary(NIP)).total_awards == 2


async def test_contractor_search_folds_accents(
    procurement: ProcurementService, http: aioresponses
) -> None:
    cassettes.bzp_notices(http, "bzp_notices_2026-10-01.json")
    await procurement.ingest_day(DAY)
    [match] = await procurement.search_contractors("PRZYKLADOWA spolka")
    assert (match.nip, match.awards) == (NIP, 2)
    assert await procurement.search_contractors("100%") == []


async def test_summary_for_unknown_nip(procurement: ProcurementService) -> None:
    summary = await procurement.summary("1111111111")
    assert (summary.total_awards, summary.recent, summary.coverage_days) == (0, [], 0)
