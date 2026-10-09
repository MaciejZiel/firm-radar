from __future__ import annotations

import re

import pytest
from aioresponses import aioresponses
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from firm_radar.identifiers import IdKind, Query
from firm_radar.models import Change, Snapshot, SourceCache
from firm_radar.services.profiles import AllSourcesFailed, CompanyNotFound, ProfileService
from firm_radar.sources import Sources
from tests import cassettes

KRS_NO = "0000999901"
NIP = "1234563218"


@pytest.fixture
def profiles(sessionmaker: async_sessionmaker[AsyncSession], sources: Sources) -> ProfileService:
    return ProfileService(sessionmaker, sources)


async def _expire_cache(sessionmaker: async_sessionmaker[AsyncSession]) -> None:
    async with sessionmaker() as session:
        await session.execute(SourceCache.__table__.delete())
        await session.commit()


async def test_resolve_by_nip_follows_to_krs(profiles: ProfileService, http: aioresponses) -> None:
    cassettes.whitelist(http, "nip", NIP, "wl_nip_1234563218.json")
    cassettes.krs_extract(http, KRS_NO, "krs_odpis_0000999901_v1.json")
    result = await profiles.resolve(Query(IdKind.NIP, NIP))
    assert result.created
    assert (result.company.krs, result.company.nip, result.company.regon) == (
        KRS_NO,
        NIP,
        "123456785",
    )
    assert [r["source"] for r in result.company.source_refs] == ["whitelist", "krs"]
    data = result.snapshot.data
    assert data["vat"]["status"] == "Czynny"
    assert data["krs"]["management"]["members"][0]["role"] == "PREZES ZARZĄDU"


async def test_same_data_does_not_create_new_snapshot(
    profiles: ProfileService, http: aioresponses
) -> None:
    cassettes.krs_extract(http, KRS_NO, "krs_odpis_0000999901_v1.json")
    cassettes.whitelist(http, "nip", NIP, "wl_nip_1234563218.json")
    first = await profiles.resolve(Query(IdKind.KRS, KRS_NO))
    again = await profiles.refresh(first.company.id)  # served from the response cache
    assert not again.created
    assert again.snapshot.id == first.snapshot.id


async def test_refresh_records_changes(
    profiles: ProfileService,
    http: aioresponses,
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    cassettes.krs_extract(http, KRS_NO, "krs_odpis_0000999901_v1.json")
    cassettes.whitelist(http, "nip", NIP, "wl_nip_1234563218.json")
    first = await profiles.resolve(Query(IdKind.KRS, KRS_NO))

    await _expire_cache(sessionmaker)
    cassettes.krs_extract(http, KRS_NO, "krs_odpis_0000999901_v2.json")
    cassettes.whitelist(http, "nip", NIP, "wl_nip_1234563218_removed.json")
    second = await profiles.refresh(first.company.id)

    assert second.created
    fields = {(c.field, c.kind) for c in second.changes}
    assert {
        ("management", "added"),
        ("address", "modified"),
        ("vat_status", "modified"),
        ("vat_accounts", "removed"),
    } <= fields
    async with sessionmaker() as session:
        stored = await session.scalar(select(func.count()).select_from(Change))
        snapshots = await session.scalar(select(func.count()).select_from(Snapshot))
    assert stored == len(second.changes)
    assert snapshots == 2

    history = await profiles.history(first.company.id)
    assert [len(changes) for _, changes in history] == [len(second.changes), 0]


async def test_whitelist_outage_keeps_previous_vat_section(
    profiles: ProfileService,
    http: aioresponses,
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    cassettes.krs_extract(http, KRS_NO, "krs_odpis_0000999901_v1.json")
    cassettes.whitelist(http, "nip", NIP, "wl_nip_1234563218.json")
    first = await profiles.resolve(Query(IdKind.KRS, KRS_NO))

    await _expire_cache(sessionmaker)
    cassettes.krs_extract(http, KRS_NO, "krs_odpis_0000999901_v1.json")
    http.get(re.compile(r".*/search/nip/.*"), status=503, repeat=True)
    second = await profiles.refresh(first.company.id)

    assert not second.created  # nothing changed: VAT data carried over, not "removed"
    refs = {r["source"]: r for r in second.company.source_refs}
    assert refs["whitelist"]["ok"] is False


async def test_unknown_krs(profiles: ProfileService, http: aioresponses) -> None:
    cassettes.krs_extract(http, KRS_NO, None, register="P")
    cassettes.krs_extract(http, KRS_NO, None, register="S")
    with pytest.raises(CompanyNotFound):
        await profiles.resolve(Query(IdKind.KRS, KRS_NO))


async def test_all_sources_down_for_new_company(
    profiles: ProfileService, http: aioresponses
) -> None:
    http.get(re.compile(r".*/search/nip/.*"), status=503, repeat=True)
    with pytest.raises(AllSourcesFailed):
        await profiles.resolve(Query(IdKind.NIP, NIP))


async def test_search_local_is_accent_insensitive(
    profiles: ProfileService, http: aioresponses
) -> None:
    cassettes.krs_extract(http, KRS_NO, "krs_odpis_0000999901_v1.json")
    cassettes.whitelist(http, "nip", NIP, "wl_nip_1234563218.json")
    await profiles.resolve(Query(IdKind.KRS, KRS_NO))
    assert [c.krs for c in await profiles.search_local("przykladowa")] == [KRS_NO]
    assert await profiles.search_local("nieistniejąca") == []
