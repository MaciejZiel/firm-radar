from __future__ import annotations

import re
from datetime import UTC, date, datetime

import pytest
from aioresponses import aioresponses
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from firm_radar.models import SourceStatus
from firm_radar.sources import Sources
from firm_radar.sources.base import BadRequest, QuotaExceeded, SourceUnavailable
from firm_radar.sources.bzp import clean_nip, parse_awards
from firm_radar.sources.krs import parse_extract
from tests import cassettes

KRS_NO = "0009999901"
NIP = "1234563218"


# --- KRS ---------------------------------------------------------------------------------------


def test_parse_krs_extract() -> None:
    data = parse_extract(cassettes.load("krs_odpis_0009999901_v1.json"))
    assert data.krs == KRS_NO
    assert data.name.startswith("PRZYKŁADOWA SPÓŁKA TESTOWA")
    assert (data.nip, data.regon) == (NIP, "123456785")
    assert data.registered_on == date(2019, 3, 15)
    assert data.last_entry_no == 7
    assert data.address is not None
    assert data.address.one_line() == "UL. PRZYKŁADOWA 1/2, 00-001 TESTOWO"
    assert data.share_capital is not None
    assert data.share_capital.amount == "5000.00"
    assert data.management is not None
    assert [m.label() for m in data.management.members] == ["PREZES ZARZĄDU: J** T*****"]
    assert [a.code for a in data.main_activity] == ["62.01.Z"]


def test_parse_tolerates_sparse_payload() -> None:
    data = parse_extract({"odpis": {"naglowekA": {"numerKRS": "42"}, "dane": {}}}, "S")
    assert (data.krs, data.registry, data.name, data.address) == ("0000000042", "S", "?", None)


async def test_krs_extract_is_cached(sources: Sources, http: aioresponses) -> None:
    cassettes.krs_extract(http, KRS_NO, "krs_odpis_0009999901_v1.json")
    first = await sources.krs.current_extract(KRS_NO)
    second = await sources.krs.current_extract(KRS_NO)  # no second response registered
    assert first is not None
    assert second is not None
    assert (first.from_cache, second.from_cache) == (False, True)
    assert second.data == first.data
    assert first.url.endswith(f"/OdpisAktualny/{KRS_NO}?rejestr=P&format=json")


async def test_krs_falls_back_to_association_register(sources: Sources, http: aioresponses) -> None:
    cassettes.krs_extract(http, KRS_NO, None, register="P")
    cassettes.krs_extract(http, KRS_NO, "krs_odpis_0009999901_v1.json", register="S")
    extract = await sources.krs.current_extract(KRS_NO)
    assert extract is not None
    assert extract.data.registry == "S"


async def test_krs_not_found_is_negative_cached(sources: Sources, http: aioresponses) -> None:
    cassettes.krs_extract(http, KRS_NO, None, register="P")
    cassettes.krs_extract(http, KRS_NO, None, register="S")
    assert await sources.krs.current_extract(KRS_NO) is None
    assert await sources.krs.current_extract(KRS_NO) is None


async def test_retries_then_succeeds(
    sources: Sources, http: aioresponses, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    url = re.compile(rf".*/OdpisAktualny/{KRS_NO}\?.*rejestr=P.*")
    http.get(url, status=503, body="<html>maintenance</html>")
    cassettes.krs_extract(http, KRS_NO, "krs_odpis_0009999901_v1.json")
    assert await sources.krs.current_extract(KRS_NO) is not None


async def test_gives_up_after_retries_and_records_error(
    sources: Sources, http: aioresponses, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    url = re.compile(rf".*/OdpisAktualny/{KRS_NO}\?.*")
    http.get(url, status=502, repeat=True)
    with pytest.raises(SourceUnavailable, match="HTTP 502"):
        await sources.krs.current_extract(KRS_NO)
    async with sessionmaker() as session:
        status = await session.scalar(select(SourceStatus).where(SourceStatus.source == "krs"))
    assert status is not None
    assert (status.requests, status.errors, status.last_error) == (1, 1, "HTTP 502")


async def test_bulletin_pads_numbers(sources: Sources, http: aioresponses) -> None:
    http.get(
        re.compile(r".*/api/Krs/Biuletyn/2026-10-01$"),
        payload=cassettes.load("krs_biuletyn.json"),
    )
    assert await sources.krs.daily_bulletin(date(2026, 10, 1)) == [
        "0000000123",
        "0009999901",
        "0009999902",
    ]


# --- VAT white list ----------------------------------------------------------------------------


async def test_whitelist_by_nip(sources: Sources, http: aioresponses) -> None:
    cassettes.whitelist(http, "nip", NIP, "wl_nip_1234563218.json")
    lookup = await sources.whitelist.by_nip(NIP)
    assert lookup.data is not None
    assert (lookup.data.status, lookup.data.krs, lookup.data.regon) == (
        "Czynny",
        KRS_NO,
        "123456785",
    )
    assert lookup.data.account_numbers == ["00000000000000000000000001"]
    assert lookup.url.startswith(f"https://wl-api.mf.gov.pl/api/search/nip/{NIP}?date=")
    cached = await sources.whitelist.by_nip(NIP)
    assert cached.from_cache


async def test_whitelist_not_found(sources: Sources, http: aioresponses) -> None:
    cassettes.whitelist(http, "nip", NIP, "wl_not_found.json")
    assert (await sources.whitelist.by_nip(NIP)).data is None


async def test_whitelist_invalid_nip(sources: Sources, http: aioresponses) -> None:
    cassettes.whitelist(http, "nip", NIP, "wl_invalid_nip.json", status=400)
    with pytest.raises(BadRequest, match="Nieprawidłowy NIP"):
        await sources.whitelist.by_nip(NIP)


async def test_whitelist_daily_budget(sources: Sources, http: aioresponses) -> None:
    for _ in range(5):  # budget in test settings
        await sources.store.record(sources.whitelist.source, ok=True)
    with pytest.raises(QuotaExceeded):
        await sources.whitelist.by_nip(NIP)
    assert not http.requests


# --- BZP ---------------------------------------------------------------------------------------


def test_clean_nip() -> None:
    assert clean_nip("NIP: 123-456-32-18") == NIP
    assert clean_nip("DE123") is None
    assert clean_nip(None) is None


def test_parse_awards_groups_lots_and_skips_invalid() -> None:
    notices = cassettes.load("bzp_notices_2026-10-01.json")
    awards = [a for n in notices for a in parse_awards(n)]
    assert [(a.bzp_number, a.contractor_nip, a.parts_won) for a in awards] == [
        ("2026/BZP 00000001", NIP, 2),
        ("2026/BZP 00000002", NIP, 1),
    ]
    first = awards[0]
    assert first.published_at == datetime(2026, 10, 1, 1, 0, tzinfo=UTC)
    assert (first.buyer_name, first.buyer_nip) == ("Gmina Testowo", "1111111111")


async def test_bzp_pagination(
    sources: Sources, http: aioresponses, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("firm_radar.sources.bzp.PAGE_SIZE", 2)
    notices = cassettes.load("bzp_notices_2026-10-01.json")
    url = re.compile(r".*/mo-board/api/v1/notice\?.*")
    http.get(url, payload=notices[:2])
    http.get(url, payload=notices[2:3])
    pages = [p async for p in sources.bzp.result_notices(date(2026, 10, 1))]
    assert [len(p) for p in pages] == [2, 1]
    calls = [call for calls in http.requests.values() for call in calls]
    assert "SearchAfter" not in calls[0].kwargs["params"]
    assert calls[1].kwargs["params"]["SearchAfter"] == notices[1]["objectId"]


async def test_bzp_stops_at_end_of_day(
    sources: Sources, http: aioresponses, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("firm_radar.sources.bzp.PAGE_SIZE", 2)
    notices = cassettes.load("bzp_notices_2026-10-01.json")
    next_day = {**notices[1], "publicationDate": "2026-10-02T00:00:01Z"}
    http.get(re.compile(r".*/mo-board/api/v1/notice\?.*"), payload=[notices[0], next_day])
    pages = [p async for p in sources.bzp.result_notices(date(2026, 10, 1))]
    assert [[n["objectId"] for n in p] for p in pages] == [[notices[0]["objectId"]]]
