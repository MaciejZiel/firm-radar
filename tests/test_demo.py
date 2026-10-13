from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from aioresponses import aioresponses
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from firm_radar.config import Settings
from firm_radar.demo import SEED_KRS, SEED_NIP, seed
from firm_radar.main import create_app
from firm_radar.services.procurement import ProcurementService
from firm_radar.services.profiles import ProfileService
from firm_radar.sources import Sources
from tests.asgi import AsgiClient


@pytest.fixture
async def demo_client(
    settings: Settings,
    sessionmaker: async_sessionmaker[AsyncSession],
    sources: Sources,
    http: aioresponses,
) -> AsyncIterator[AsgiClient]:
    assert await seed(
        sessionmaker,
        ProfileService(sessionmaker, sources),
        ProcurementService(sessionmaker, sources.bzp),
    )
    demo = settings.model_copy(
        update={"demo_mode": True, "scheduler_enabled": True, "demo_rate_limit_per_minute": 5}
    )
    app = create_app(demo)
    async with app.router.lifespan_context(app):
        assert app.state.scheduler is None
        yield AsgiClient(app)


async def test_seed_is_idempotent(
    sessionmaker: async_sessionmaker[AsyncSession], sources: Sources, http: aioresponses
) -> None:
    profiles = ProfileService(sessionmaker, sources)
    procurement = ProcurementService(sessionmaker, sources.bzp)
    assert await seed(sessionmaker, profiles, procurement)
    assert not await seed(sessionmaker, profiles, procurement)


async def test_seeded_company_has_history_and_awards(demo_client: AsgiClient) -> None:
    found = (await demo_client.get("/api/v1/search", params={"q": SEED_NIP})).json()
    company_id = found["results"][0]["id"]
    history = (await demo_client.get(f"/api/v1/companies/{company_id}/history")).json()
    assert history["snapshots"] == 2
    assert history["timeline"][0]["changes"]
    profile = (await demo_client.get(f"/api/v1/companies/{company_id}")).json()
    assert profile["procurement"]["total_awards"] >= 1


async def test_unknown_identifier_never_reaches_the_registries(demo_client: AsgiClient) -> None:
    # `http` blocks real requests: any registry call would raise instead of answering.
    response = await demo_client.get("/api/v1/search", params={"q": "5260250995"})
    assert response.status_code == 200
    body = response.json()
    assert body["results"] == []
    assert "Demo mode" in body["note"]
    assert (await demo_client.get("/szukaj", params={"q": SEED_KRS})).status_code == 303


async def test_writes_are_rejected(demo_client: AsgiClient) -> None:
    api = await demo_client.post("/api/v1/companies/1/refresh")
    web = await demo_client.post("/firma/1/odswiez")
    assert (api.status_code, web.status_code) == (403, 403)


async def test_web_shows_banner_without_refresh_button(demo_client: AsgiClient) -> None:
    found = (await demo_client.get("/api/v1/search", params={"q": SEED_NIP})).json()
    page = await demo_client.get(f"/firma/{found['results'][0]['id']}")
    assert 'class="demo-banner"' in page.text
    assert "/odswiez" not in page.text


async def test_rate_limit(demo_client: AsgiClient) -> None:
    codes = [(await demo_client.get("/api/v1/sources/health")).status_code for _ in range(7)]
    assert codes == [200] * 5 + [429] * 2
    assert (await demo_client.get("/healthz")).status_code == 200
    limited = await demo_client.get("/api/v1/sources/health")
    assert int(limited.headers["retry-after"]) >= 1
