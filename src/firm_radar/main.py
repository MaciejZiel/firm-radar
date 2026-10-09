"""ASGI application factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from firm_radar import __version__
from firm_radar.config import Settings, get_settings
from firm_radar.db import Database


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        database = Database(settings.database_url, echo=settings.sql_echo)
        app.state.db = database
        try:
            yield
        finally:
            await database.dispose()

    app = FastAPI(title="firm-radar", version=__version__, lifespan=lifespan)
    app.state.settings = settings

    @app.get("/healthz", tags=["meta"], summary="Liveness probe")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app
