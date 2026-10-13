"""Public demo mode: a fictional seed dataset and a guard that keeps the service read-only.

In demo mode the service never calls the registries and runs no background jobs. The seed
data is the same fictional company the tests use (a company that does not exist), with two
snapshots so the change timeline has something to show.
"""

from __future__ import annotations

import json
import time
from collections import deque
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.types import ASGIApp, Receive, Scope, Send

from firm_radar.models import Company
from firm_radar.schemas import SourceRef
from firm_radar.services.procurement import ProcurementService
from firm_radar.services.profiles import Collected, ProfileService
from firm_radar.sources.base import utcnow
from firm_radar.sources.krs import parse_extract
from firm_radar.sources.whitelist import parse_vat

DATA = Path(__file__).parent / "demo_data"
SEED_NIP = "1234563218"
SEED_KRS = "0009999901"
BZP_DAY = date(2026, 10, 1)
NOTE = "Fictional demo data"

# Shown as clickable examples on the search page in demo mode.
DEMO_EXAMPLES = [(SEED_NIP, "Przykładowa Spółka Testowa")]


def _load(name: str) -> Any:
    return json.loads((DATA / name).read_text(encoding="utf-8"))


def _collected(krs_file: str, vat_file: str, at: datetime) -> Collected:
    krs = parse_extract(_load(krs_file), "P")
    vat = parse_vat(_load(vat_file))
    return Collected(
        krs=krs,
        vat=vat,
        vat_checked=True,
        refs=[
            SourceRef(
                source="krs",
                label="KRS – odpis aktualny",
                url="https://prs.ms.gov.pl/krs/openApi",
                fetched_at=at,
                note=NOTE,
            ),
            SourceRef(
                source="whitelist",
                label="Biała lista VAT",
                url="https://www.gov.pl/web/kas/api-wykazu-podatnikow-vat",
                fetched_at=at,
                note=NOTE,
            ),
        ],
    )


async def seed(
    sessionmaker: async_sessionmaker[AsyncSession],
    profiles: ProfileService,
    procurement: ProcurementService,
) -> bool:
    """Load the fictional dataset. Returns False (and changes nothing) if companies exist."""
    async with sessionmaker() as session:
        existing = await session.scalar(select(func.count()).select_from(Company))
    if existing:
        return False
    now = utcnow()
    first = now - timedelta(days=30)
    second = now - timedelta(days=2)
    await profiles.store(
        _collected("krs_odpis_0009999901_v1.json", "wl_nip_1234563218.json", first), now=first
    )
    await profiles.store(
        _collected("krs_odpis_0009999901_v2.json", "wl_nip_1234563218_removed.json", second),
        now=second,
    )
    await procurement.import_notices(BZP_DAY, _load("bzp_notices_2026-10-01.json"))
    return True


class DemoGuard:
    """ASGI middleware: GET/HEAD/OPTIONS only, plus a per-client request budget per minute."""

    SAFE = frozenset({"GET", "HEAD", "OPTIONS"})
    WINDOW_S = 60.0
    MAX_CLIENTS = 5000

    def __init__(self, app: ASGIApp, limit_per_minute: int = 60) -> None:
        self.app = app
        self.limit = limit_per_minute
        self._hits: dict[str, deque[float]] = {}

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = scope["path"]
        if scope["method"] not in self.SAFE:
            await self._reply(send, 403, "This demo is read-only.")
            return
        if self.limit and path != "/healthz" and not path.startswith("/static/"):
            client = (scope.get("client") or ("unknown", 0))[0]
            wait = self._check(client)
            if wait:
                await self._reply(
                    send, 429, "Too many requests, slow down.", {"retry-after": str(wait)}
                )
                return
        await self.app(scope, receive, send)

    def _check(self, client: str) -> int:
        """Record a hit; return seconds to wait when the client is over budget, else 0."""
        now = time.monotonic()
        hits = self._hits.setdefault(client, deque())
        while hits and now - hits[0] > self.WINDOW_S:
            hits.popleft()
        if len(hits) >= self.limit:
            return max(1, int(self.WINDOW_S - (now - hits[0])) + 1)
        hits.append(now)
        if len(self._hits) > self.MAX_CLIENTS:
            self._hits = {c: h for c, h in self._hits.items() if h and now - h[-1] <= self.WINDOW_S}
        return 0

    @staticmethod
    async def _reply(
        send: Send, status: int, detail: str, headers: dict[str, str] | None = None
    ) -> None:
        body = json.dumps({"detail": detail}).encode()
        raw = [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]
        raw += [(k.encode(), v.encode()) for k, v in (headers or {}).items()]
        await send({"type": "http.response.start", "status": status, "headers": raw})
        await send({"type": "http.response.body", "body": body})
