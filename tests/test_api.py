from __future__ import annotations

from aioresponses import aioresponses
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from firm_radar.models import SourceCache
from tests import cassettes
from tests.asgi import AsgiClient

KRS_NO = "0000999901"
NIP = "1234563218"


def _register_v1(http: aioresponses) -> None:
    cassettes.krs_extract(http, KRS_NO, "krs_odpis_0000999901_v1.json")
    cassettes.whitelist(http, "nip", NIP, "wl_nip_1234563218.json")


async def test_healthz(client: AsgiClient) -> None:
    response = await client.get("/healthz")
    assert (response.status_code, response.json()) == (200, {"status": "ok"})


async def test_openapi_documents_endpoints(client: AsgiClient) -> None:
    spec = (await client.get("/openapi.json")).json()
    assert {
        "/api/v1/search",
        "/api/v1/companies/{company_id}",
        "/api/v1/companies/{company_id}/history",
        "/api/v1/companies/{company_id}/diff",
    } <= set(spec["paths"])
    assert spec["components"]["schemas"]["CompanySummary"]["example"]["nip"] == NIP


async def test_search_by_krs_and_profile(client: AsgiClient, http: aioresponses) -> None:
    _register_v1(http)
    found = (await client.get("/api/v1/search", params={"q": "999901"})).json()
    assert (found["kind"], found["value"]) == ("krs", KRS_NO)
    [company] = found["results"]
    assert company["nip"] == NIP

    profile = await client.get(f"/api/v1/companies/{company['id']}")
    body = profile.json()
    assert profile.status_code == 200
    assert body["data"]["vat"]["status"] == "Czynny"
    assert {s["source"] for s in body["sources"]} == {"krs", "whitelist"}


async def test_search_by_name_uses_local_index(client: AsgiClient, http: aioresponses) -> None:
    empty = (await client.get("/api/v1/search", params={"q": "testowa"})).json()
    assert empty["results"] == []
    assert empty["note"]
    _register_v1(http)
    await client.get("/api/v1/search", params={"q": f"krs:{KRS_NO}"})
    found = (await client.get("/api/v1/search", params={"q": "Spółka Testowa"})).json()
    assert [c["krs"] for c in found["results"]] == [KRS_NO]


async def test_search_rejects_bad_identifier(client: AsgiClient) -> None:
    response = await client.get("/api/v1/search", params={"q": "nip:1234563219"})
    assert response.status_code == 400
    assert "invalid NIP" in response.json()["detail"]


async def test_unknown_company_returns_empty_results(
    client: AsgiClient, http: aioresponses
) -> None:
    cassettes.whitelist(http, "nip", NIP, "wl_not_found.json")
    found = (await client.get("/api/v1/search", params={"q": NIP})).json()
    assert found["results"] == []


async def test_upstream_down_is_503(client: AsgiClient, http: aioresponses) -> None:
    import re

    http.get(re.compile(r".*/search/nip/.*"), status=500, repeat=True)
    response = await client.get("/api/v1/search", params={"q": NIP})
    assert response.status_code == 503


async def test_refresh_history_and_diff(
    client: AsgiClient, http: aioresponses, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    _register_v1(http)
    company_id = (await client.get("/api/v1/search", params={"q": KRS_NO})).json()["results"][0][
        "id"
    ]
    async with sessionmaker() as session:
        await session.execute(SourceCache.__table__.delete())
        await session.commit()
    cassettes.krs_extract(http, KRS_NO, "krs_odpis_0000999901_v2.json")
    cassettes.whitelist(http, "nip", NIP, "wl_nip_1234563218.json")

    refreshed = (await client.post(f"/api/v1/companies/{company_id}/refresh")).json()
    assert refreshed["new_snapshot"] is True
    assert {
        "field": "management",
        "kind": "added",
        "old": None,
        "new": "CZŁONEK ZARZĄDU: A*** N****",
    } in refreshed["changes"]

    history = (await client.get(f"/api/v1/companies/{company_id}/history")).json()
    assert history["snapshots"] == 2
    assert history["timeline"][0]["changes"] == refreshed["changes"]

    latest = (await client.get(f"/api/v1/companies/{company_id}/diff")).json()
    assert latest["changes"] == refreshed["changes"]
    first, second = history["timeline"][1]["snapshot_id"], history["timeline"][0]["snapshot_id"]
    reverse = (
        await client.get(
            f"/api/v1/companies/{company_id}/diff", params={"from": str(second), "to": str(first)}
        )
    ).json()
    assert {
        "field": "management",
        "kind": "removed",
        "old": "CZŁONEK ZARZĄDU: A*** N****",
        "new": None,
    } in reverse["changes"]


async def test_missing_company(client: AsgiClient) -> None:
    assert (await client.get("/api/v1/companies/999")).status_code == 404
    assert (await client.get("/api/v1/companies/999/history")).status_code == 404
    assert (await client.get("/api/v1/companies/999/diff")).status_code == 404


async def test_sources_health(client: AsgiClient, http: aioresponses) -> None:
    _register_v1(http)
    await client.get("/api/v1/search", params={"q": KRS_NO})
    health = (await client.get("/api/v1/sources/health")).json()
    by_source = {s["source"]: s for s in health["sources"]}
    assert set(by_source) == {"krs", "whitelist", "bzp"}
    assert by_source["krs"]["status"] == "ok"
    assert by_source["whitelist"]["budget_left"] == by_source["whitelist"]["daily_budget"] - 1
    assert by_source["bzp"]["status"] == "unknown"
    assert health["bzp_coverage"]["days"] == 0


async def test_name_search_suggests_bzp_contractors(
    client: AsgiClient, http: aioresponses, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    from datetime import date

    from firm_radar.services.procurement import ProcurementService
    from firm_radar.sources import Sources

    cassettes.bzp_notices(http, "bzp_notices_2026-10-01.json")
    sources: Sources = client.app.state.sources  # type: ignore[attr-defined]
    await ProcurementService(sessionmaker, sources.bzp).ingest_day(date(2026, 10, 1))

    found = (await client.get("/api/v1/search", params={"q": "przykładowa"})).json()
    assert found["results"] == []
    assert found["candidates"] == [
        {"name": "Przykładowa Spółka Testowa sp. z o.o.", "nip": NIP, "awards": 2, "source": "bzp"}
    ]

    _register_v1(http)
    company_id = (await client.get("/api/v1/search", params={"q": NIP})).json()["results"][0]["id"]
    profile = (await client.get(f"/api/v1/companies/{company_id}")).json()
    assert profile["procurement"]["total_awards"] == 2
    assert profile["procurement"]["recent"][0]["notice_url"].endswith(
        "noticeId=00000000-0000-0000-0000-000000000002"
    )
