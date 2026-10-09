"""ASGI application factory."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import aiohttp
from fastapi import FastAPI

from firm_radar import __version__
from firm_radar.api.routes import router as api_router
from firm_radar.config import Settings, get_settings
from firm_radar.db import Database
from firm_radar.services.jobs import JobRunner, Scheduler
from firm_radar.services.procurement import ProcurementService
from firm_radar.services.profiles import ProfileService
from firm_radar.sources import Sources
from firm_radar.sources.store import PgSourceStore

DESCRIPTION = """
Company profiles assembled from official Polish public registries:

* **KRS** – open API of the Ministry of Justice (current extract, daily change bulletin),
* **VAT white list** – Ministry of Finance taxpayer register,
* **BZP** – contract award notices from the Public Procurement Bulletin.

Every profile is stored as a snapshot; when the registries report something different, the
difference is recorded as field-level changes (board members, address, VAT status, ...).
Upstream responses are cached in PostgreSQL with a TTL, so repeated lookups stay within the
registries' fair-use limits.
"""

TAGS = [
    {"name": "companies", "description": "Lookup and profiles"},
    {"name": "history", "description": "Snapshots and detected changes"},
    {"name": "meta", "description": "Service health"},
]


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        database = Database(settings.database_url, echo=settings.sql_echo)
        http = aiohttp.ClientSession()
        store = PgSourceStore(database.sessionmaker)
        sources = Sources.build(http, settings, store)
        app.state.db = database
        app.state.sources = sources
        profiles = ProfileService(database.sessionmaker, sources)
        procurement = ProcurementService(database.sessionmaker, sources.bzp)
        app.state.profiles = profiles
        app.state.procurement = procurement
        scheduler: Scheduler | None = None
        if settings.scheduler_enabled:
            runner = JobRunner(settings, database.sessionmaker, sources, profiles, procurement)
            scheduler = Scheduler(runner, settings.refresh_interval_s)
            scheduler.start()
        app.state.scheduler = scheduler
        try:
            yield
        finally:
            if scheduler is not None:
                await scheduler.stop()
            await http.close()
            await database.dispose()

    app = FastAPI(
        title="firm-radar",
        version=__version__,
        description=DESCRIPTION,
        openapi_tags=TAGS,
        lifespan=lifespan,
        license_info={"name": "MIT", "identifier": "MIT"},
    )
    app.state.settings = settings
    app.include_router(api_router)

    @app.get("/healthz", tags=["meta"], summary="Liveness probe")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app
