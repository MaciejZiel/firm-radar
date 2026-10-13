"""Local index of BZP contract awards, keyed by contractor NIP."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from firm_radar.identifiers import like_pattern, search_key
from firm_radar.models import BzpIngestDay, ProcurementAward
from firm_radar.sources.base import today, utcnow
from firm_radar.sources.bzp import BzpClient, parse_awards

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class IngestResult:
    day: date
    notices: int
    awards: int
    skipped: bool = False


@dataclass(frozen=True, slots=True)
class AwardSummary:
    total_awards: int
    total_lots: int
    recent: list[ProcurementAward]
    coverage_from: date | None
    coverage_to: date | None
    coverage_days: int


@dataclass(frozen=True, slots=True)
class Contractor:
    nip: str
    name: str
    awards: int


class ProcurementService:
    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession], client: BzpClient) -> None:
        self._sessionmaker = sessionmaker
        self._client = client

    async def ingest_day(self, day: date, *, force: bool = False) -> IngestResult:
        async with self._sessionmaker() as session:
            done = await session.get(BzpIngestDay, day)
        if done is not None and not force:
            return IngestResult(day, done.notices, done.awards, skipped=True)

        notices = awards = 0
        async for page in self._client.result_notices(day):
            notices += len(page)
            awards += await self._store_page(page)
        await self._mark_day(day, notices, awards)
        log.info("BZP %s: %d award notices, %d contractor awards", day, notices, awards)
        return IngestResult(day, notices, awards)

    async def import_notices(self, day: date, notices: list[dict[str, Any]]) -> IngestResult:
        """Store already-fetched notices for ``day`` (used to seed the demo dataset)."""
        awards = await self._store_page(notices)
        await self._mark_day(day, len(notices), awards)
        return IngestResult(day, len(notices), awards)

    async def _store_page(self, page: list[dict[str, Any]]) -> int:
        rows = [a for notice in page for a in parse_awards(notice)]
        if not rows:
            return 0
        stmt = insert(ProcurementAward).values(
            [
                {
                    "notice_id": a.notice_id,
                    "bzp_number": a.bzp_number,
                    "tender_id": a.tender_id,
                    "published_at": a.published_at,
                    "order_type": a.order_type,
                    "order_object": a.order_object,
                    "cpv": a.cpv,
                    "buyer_name": a.buyer_name,
                    "buyer_nip": a.buyer_nip,
                    "buyer_city": a.buyer_city,
                    "contractor_nip": a.contractor_nip,
                    "contractor_name": a.contractor_name,
                    "contractor_city": a.contractor_city,
                    "parts_won": a.parts_won,
                }
                for a in rows
            ]
        )
        stmt = stmt.on_conflict_do_update(
            constraint="uq_procurement_awards_notice_nip",
            set_={
                "parts_won": stmt.excluded.parts_won,
                "order_object": stmt.excluded.order_object,
            },
        )
        async with self._sessionmaker() as session:
            await session.execute(stmt)
            await session.commit()
        return len(rows)

    async def _mark_day(self, day: date, notices: int, awards: int) -> None:
        marker = insert(BzpIngestDay).values(
            day=day, notices=notices, awards=awards, ingested_at=utcnow()
        )
        marker = marker.on_conflict_do_update(
            index_elements=["day"],
            set_={"notices": notices, "awards": awards, "ingested_at": marker.excluded.ingested_at},
        )
        async with self._sessionmaker() as session:
            await session.execute(marker)
            await session.commit()

    async def ingest_recent(self, days: int) -> list[IngestResult]:
        """Ingest complete days only: from ``days`` days ago up to yesterday."""
        last = today() - timedelta(days=1)
        return [await self.ingest_day(last - timedelta(days=i)) for i in range(days)]

    async def summary(self, nip: str, limit: int = 10) -> AwardSummary:
        async with self._sessionmaker() as session:
            totals = (
                await session.execute(
                    select(
                        func.count(ProcurementAward.id),
                        func.coalesce(func.sum(ProcurementAward.parts_won), 0),
                    ).where(ProcurementAward.contractor_nip == nip)
                )
            ).one()
            recent = list(
                await session.scalars(
                    select(ProcurementAward)
                    .where(ProcurementAward.contractor_nip == nip)
                    .order_by(ProcurementAward.published_at.desc())
                    .limit(limit)
                )
            )
            coverage = (
                await session.execute(
                    select(
                        func.min(BzpIngestDay.day),
                        func.max(BzpIngestDay.day),
                        func.count(BzpIngestDay.day),
                    )
                )
            ).one()
        return AwardSummary(
            total_awards=int(totals[0]),
            total_lots=int(totals[1]),
            recent=recent,
            coverage_from=coverage[0],
            coverage_to=coverage[1],
            coverage_days=int(coverage[2]),
        )

    async def search_contractors(self, text: str, limit: int = 10) -> list[Contractor]:
        """Contractors from BZP whose name matches; lets users find companies by name.

        ``awards`` counts every award of the NIP, also those published under another name.
        """
        name_key = func.lower(func.translate(ProcurementAward.contractor_name, _FROM, _TO))
        matching = (
            select(
                ProcurementAward.contractor_nip.label("nip"),
                func.max(ProcurementAward.contractor_name).label("name"),
            )
            .where(name_key.like(like_pattern(search_key(text))))
            .group_by(ProcurementAward.contractor_nip)
            .subquery()
        )
        awards = func.count(ProcurementAward.id)
        async with self._sessionmaker() as session:
            rows = await session.execute(
                select(matching.c.nip, matching.c.name, awards)
                .join(ProcurementAward, ProcurementAward.contractor_nip == matching.c.nip)
                .group_by(matching.c.nip, matching.c.name)
                .order_by(awards.desc(), matching.c.name)
                .limit(limit)
            )
            return [Contractor(nip=r[0], name=r[1], awards=int(r[2])) for r in rows]


# Polish diacritics folded like identifiers.search_key, but in SQL.
_FROM = "ąćęłńóśźżĄĆĘŁŃÓŚŹŻ"
_TO = "acelnoszzACELNOSZZ"
