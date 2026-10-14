from __future__ import annotations

from aioresponses import aioresponses
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from firm_radar.models import SourceCache
from tests import cassettes
from tests.asgi import AsgiClient

KRS_NO = "0009999901"
NIP = "1234563218"


def _register_v1(http: aioresponses) -> None:
    cassettes.krs_extract(http, KRS_NO, "krs_odpis_0009999901_v1.json")
    cassettes.whitelist(http, "nip", NIP, "wl_nip_1234563218.json")


async def test_home_is_polish_by_default(client: AsgiClient) -> None:
    page = await client.get("/")
    assert page.status_code == 200
    assert '<html lang="pl">' in page.text
    assert "Sprawdź" in page.text
    assert "htmx-2.0.10.min.js" in page.text


async def test_language_toggle_sets_cookie(client: AsgiClient) -> None:
    page = await client.get("/", params={"lang": "en"})
    assert '<html lang="en">' in page.text
    assert "Look up" in page.text
    assert "lang=en" in page.headers["set-cookie"]
    again = await client.get("/", cookies={"lang": "en"})
    assert '<html lang="en">' in again.text


async def test_identifier_search_redirects_to_profile(
    client: AsgiClient, http: aioresponses
) -> None:
    _register_v1(http)
    response = await client.get("/szukaj", params={"q": KRS_NO})
    assert response.status_code == 303
    location = response.headers["location"]
    assert location.startswith("/firma/")

    profile = await client.get(location)
    assert profile.status_code == 200
    assert "PRZYKŁADOWA SPÓŁKA TESTOWA" in profile.text
    assert "Czynny podatnik VAT" in profile.text
    assert "5 000,00 zł" in profile.text
    assert "J** T*****" in profile.text


async def test_htmx_search_uses_hx_redirect(client: AsgiClient, http: aioresponses) -> None:
    _register_v1(http)
    response = await client.get("/szukaj", params={"q": KRS_NO}, headers={"HX-Request": "true"})
    assert response.headers["hx-redirect"].startswith("/firma/")


async def test_htmx_name_search_renders_partial(client: AsgiClient) -> None:
    response = await client.get(
        "/szukaj", params={"q": "nic takiego"}, headers={"HX-Request": "true"}
    )
    assert response.status_code == 200
    assert "<html" not in response.text
    assert "Nic nie znaleziono" in response.text


async def test_bad_identifier_shows_error(client: AsgiClient) -> None:
    response = await client.get("/szukaj", params={"q": "nip:1234563219"})
    assert response.status_code == 200
    assert "invalid NIP" in response.text


async def test_refresh_and_compare(client: AsgiClient, http: aioresponses) -> None:
    _register_v1(http)
    location = (await client.get("/szukaj", params={"q": KRS_NO})).headers["location"]
    refreshed = await client.post(f"{location}/odswiez")
    assert (refreshed.status_code, refreshed.headers["location"]) == (303, location)
    compare = await client.get(f"{location}/porownaj")
    assert compare.status_code == 200
    assert "bez zmian" in compare.text


async def test_unknown_company_page(client: AsgiClient) -> None:
    assert (await client.get("/firma/12345")).status_code == 404


async def test_sources_page(client: AsgiClient) -> None:
    page = await client.get("/zrodla")
    assert page.status_code == 200
    assert "100 zapytań dziennie" in page.text
    assert "https://prs.ms.gov.pl/krs/openApi" in page.text


async def test_timeline_and_compare_show_changes(
    client: AsgiClient, http: aioresponses, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    _register_v1(http)
    location = (await client.get("/szukaj", params={"q": KRS_NO})).headers["location"]
    async with sessionmaker() as session:
        await session.execute(SourceCache.__table__.delete())
        await session.commit()
    cassettes.krs_extract(http, KRS_NO, "krs_odpis_0009999901_v2.json")
    cassettes.whitelist(http, "nip", NIP, "wl_nip_1234563218.json")
    await client.post(f"{location}/odswiez")

    page = await client.get(location)
    assert page.status_code == 200
    assert "A*** N****" in page.text
    assert "UL. ZMYŚLONA 10" in page.text

    english = await client.get(f"{location}/porownaj", params={"lang": "en"})
    assert english.status_code == 200
    assert "Management board" in english.text
    assert "added" in english.text
