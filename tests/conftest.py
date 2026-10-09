from __future__ import annotations

import os
from collections.abc import AsyncIterator, Iterator

import aiohttp
import pytest
from aioresponses import aioresponses
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from firm_radar import models  # noqa: F401
from firm_radar.config import Settings
from firm_radar.db import Base
from firm_radar.main import create_app
from firm_radar.sources import Sources
from firm_radar.sources.store import PgSourceStore
from tests.asgi import AsgiClient

TEST_DB = os.environ.get(
    "FIRM_RADAR_TEST_DATABASE_URL",
    "postgresql+asyncpg://firm_radar:firm_radar@localhost:55433/firm_radar_test",
)


@pytest.fixture(scope="session")
def settings() -> Settings:
    return Settings(
        database_url=TEST_DB,
        http_retries=2,
        http_backoff_s=0.0,
        scheduler_enabled=False,
        whitelist_daily_budget=5,
    )


@pytest.fixture(scope="session")
async def engine(settings: Settings) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(settings.database_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
async def sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    tables = ", ".join(t.name for t in Base.metadata.sorted_tables)
    async with engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
    return async_sessionmaker(engine, expire_on_commit=False)


@pytest.fixture
def http() -> Iterator[aioresponses]:
    """Block real HTTP; tests register the responses they expect."""
    with aioresponses() as mock:
        yield mock


@pytest.fixture
async def sources(
    settings: Settings, sessionmaker: async_sessionmaker[AsyncSession], http: aioresponses
) -> AsyncIterator[Sources]:
    async with aiohttp.ClientSession() as session:
        yield Sources.build(session, settings, PgSourceStore(sessionmaker))


@pytest.fixture
async def client(
    settings: Settings, sessionmaker: async_sessionmaker[AsyncSession], http: aioresponses
) -> AsyncIterator[AsgiClient]:
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        yield AsgiClient(app)
