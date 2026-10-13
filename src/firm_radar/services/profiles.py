"""Resolve identifiers, merge registry data, and keep a change-tracked snapshot history."""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from firm_radar.identifiers import IdKind, Query, like_pattern, search_key
from firm_radar.models import Change, Company, Snapshot
from firm_radar.schemas import CompanyData, Identifiers, KrsData, SourceRef, VatData
from firm_radar.services.diff import FieldChange, diff
from firm_radar.sources import Sources
from firm_radar.sources.base import BadRequest, SourceError, SourceName, utcnow
from firm_radar.sources.krs import KrsExtract
from firm_radar.sources.whitelist import VatLookup

log = logging.getLogger(__name__)


class CompanyNotFound(Exception):
    """No registry knows the identifier."""


class InvalidQuery(Exception):
    """The registry rejected the identifier as malformed."""


class AllSourcesFailed(Exception):
    """Every registry we needed was unavailable; nothing can be shown or stored."""


@dataclass
class Collected:
    krs: KrsData | None = None
    vat: VatData | None = None
    vat_checked: bool = False
    refs: list[SourceRef] = field(default_factory=list)
    failed: set[SourceName] = field(default_factory=set)


@dataclass(frozen=True, slots=True)
class RefreshResult:
    company: Company
    snapshot: Snapshot
    created: bool
    changes: list[FieldChange]


def merge(collected: Collected, previous: CompanyData | None = None) -> CompanyData:
    """Combine registry sections; a section whose source failed is carried over from before.

    Without the carry-over a temporary outage of one API would be recorded as, e.g., "VAT
    status removed" followed by "VAT status added" once the API is back.
    """
    krs = collected.krs
    vat = collected.vat
    vat_registered: bool | None = (vat is not None) if collected.vat_checked else None
    if previous is not None:
        if SourceName.KRS in collected.failed and krs is None:
            krs = previous.krs
        if SourceName.WHITELIST in collected.failed and not collected.vat_checked:
            vat, vat_registered = previous.vat, previous.vat_registered

    if krs is None and vat is None:
        raise CompanyNotFound
    name = krs.name if krs else vat.name if vat else "?"
    address = krs.address.one_line() if krs and krs.address else None
    if not address and vat:
        address = vat.working_address or vat.residence_address
    return CompanyData(
        identifiers=Identifiers(
            krs=krs.krs if krs else (vat.krs if vat else None),
            nip=(krs.nip if krs else None) or (vat.nip if vat else None),
            regon=(krs.regon if krs else None) or (vat.regon if vat else None),
        ),
        name=name,
        legal_form=krs.legal_form if krs else None,
        address=address,
        city=krs.address.city if krs and krs.address else None,
        krs=krs,
        vat=vat,
        vat_registered=vat_registered,
    )


def content_hash(data: CompanyData) -> str:
    canonical = json.dumps(data.model_dump(mode="json"), sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()


class ProfileService:
    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession], sources: Sources) -> None:
        self._sessionmaker = sessionmaker
        self._sources = sources

    # --- collecting ----------------------------------------------------------------------------

    async def _krs(self, krs: str, out: Collected) -> None:
        try:
            extract: KrsExtract | None = await self._sources.krs.current_extract(krs)
        except SourceError as exc:
            out.failed.add(SourceName.KRS)
            out.refs.append(
                SourceRef(
                    source="krs",
                    label="KRS",
                    url=self._sources.krs.extract_url(krs),
                    ok=False,
                    note=exc.message,
                )
            )
            return
        if extract is not None:
            out.krs = extract.data
            out.refs.append(
                SourceRef(
                    source="krs",
                    label="KRS – odpis aktualny",
                    url=extract.url,
                    fetched_at=extract.fetched_at,
                    from_cache=extract.from_cache,
                )
            )

    async def _vat(self, kind: str, value: str, out: Collected) -> None:
        client = self._sources.whitelist
        try:
            lookup: VatLookup = await (
                client.by_nip(value) if kind == "nip" else client.by_regon(value)
            )
        except BadRequest as exc:
            raise InvalidQuery(exc.message) from exc
        except SourceError as exc:
            out.failed.add(SourceName.WHITELIST)
            out.refs.append(
                SourceRef(
                    source="whitelist",
                    label="Biała lista VAT",
                    url=client.search_url(kind, value),
                    ok=False,
                    note=exc.message,
                )
            )
            return
        out.vat, out.vat_checked = lookup.data, True
        out.refs.append(
            SourceRef(
                source="whitelist",
                label="Biała lista VAT",
                url=lookup.url,
                fetched_at=lookup.fetched_at,
                from_cache=lookup.from_cache,
            )
        )

    async def collect(self, query: Query) -> Collected:
        out = Collected()
        if query.kind is IdKind.KRS:
            await self._krs(query.value, out)
            if out.krs and out.krs.nip:
                await self._vat("nip", out.krs.nip, out)
        elif query.kind in (IdKind.NIP, IdKind.REGON):
            await self._vat(query.kind.value, query.value, out)
            krs_no = out.vat.krs if out.vat else None
            if krs_no:
                await self._krs(krs_no, out)
        else:
            raise ValueError("collect() needs an identifier, not a name")
        return out

    # --- persistence ---------------------------------------------------------------------------

    async def _find(self, session: AsyncSession, ids: Identifiers) -> Company | None:
        conditions = []
        if ids.krs:
            conditions.append(Company.krs == ids.krs)
        if ids.nip:
            conditions.append(Company.nip == ids.nip)
        if not conditions:
            return None
        found: Company | None = await session.scalar(
            select(Company).where(or_(*conditions)).limit(1)
        )
        return found

    async def find_local(self, query: Query) -> Company | None:
        column = {IdKind.KRS: Company.krs, IdKind.NIP: Company.nip, IdKind.REGON: Company.regon}
        async with self._sessionmaker() as session:
            found: Company | None = await session.scalar(
                select(Company).where(column[query.kind] == query.value).limit(1)
            )
        return found

    async def latest_snapshot(self, session: AsyncSession, company_id: int) -> Snapshot | None:
        latest: Snapshot | None = await session.scalar(
            select(Snapshot)
            .where(Snapshot.company_id == company_id)
            .order_by(Snapshot.taken_at.desc(), Snapshot.id.desc())
            .limit(1)
        )
        return latest

    async def resolve(self, query: Query) -> RefreshResult:
        """Fetch a company by identifier, store/refresh it and return the outcome."""
        collected = await self.collect(query)
        return await self._store(collected, company_id=None)

    async def refresh(self, company_id: int) -> RefreshResult:
        async with self._sessionmaker() as session:
            company = await session.get(Company, company_id)
            if company is None:
                raise CompanyNotFound
        if company.krs:
            query = Query(IdKind.KRS, company.krs)
        elif company.nip:
            query = Query(IdKind.NIP, company.nip)
        else:
            raise CompanyNotFound
        collected = await self.collect(query)
        return await self._store(collected, company_id=company_id)

    async def store(self, collected: Collected, *, now: datetime | None = None) -> RefreshResult:
        """Persist registry data that was gathered elsewhere (used to seed the demo dataset)."""
        return await self._store(collected, company_id=None, now=now)

    async def _store(
        self, collected: Collected, company_id: int | None, now: datetime | None = None
    ) -> RefreshResult:
        now = now or utcnow()
        async with self._sessionmaker() as session, session.begin():
            company: Company | None = None
            if company_id is not None:
                company = await session.get(Company, company_id, with_for_update=True)
            previous_snapshot: Snapshot | None = None
            previous: CompanyData | None = None

            if company is None and (collected.krs or collected.vat):
                ids = Identifiers(
                    krs=collected.krs.krs if collected.krs else None,
                    nip=(collected.krs.nip if collected.krs else None)
                    or (collected.vat.nip if collected.vat else None),
                )
                company = await self._find(session, ids)
            if company is not None:
                previous_snapshot = await self.latest_snapshot(session, company.id)
                if previous_snapshot is not None:
                    previous = CompanyData.model_validate(previous_snapshot.data)

            nothing_fetched = not collected.krs and not collected.vat
            if nothing_fetched and collected.failed and previous is None:
                raise AllSourcesFailed(", ".join(sorted(collected.failed)))
            data = merge(collected, previous)

            if company is None:
                company = Company(name=data.name, name_search=search_key(data.name))
                session.add(company)
            company.krs = data.identifiers.krs or company.krs
            company.nip = data.identifiers.nip or company.nip
            company.regon = data.identifiers.regon or company.regon
            company.name = data.name
            company.name_search = search_key(data.name)
            company.legal_form = data.legal_form
            company.city = data.city
            company.last_checked_at = now
            company.source_refs = [r.model_dump(mode="json") for r in collected.refs]
            await session.flush()

            digest = content_hash(data)
            if previous_snapshot is not None and previous_snapshot.content_hash == digest:
                return RefreshResult(company, previous_snapshot, created=False, changes=[])

            snapshot = Snapshot(
                company_id=company.id,
                taken_at=now,
                content_hash=digest,
                data=data.model_dump(mode="json"),
            )
            session.add(snapshot)
            await session.flush()
            changes = diff(previous, data) if previous is not None else []
            session.add_all(
                Change(
                    company_id=company.id,
                    snapshot_id=snapshot.id,
                    detected_at=now,
                    field=c.field,
                    kind=c.kind,
                    old_value=c.old,
                    new_value=c.new,
                )
                for c in changes
            )
            log.info(
                "snapshot %s for company %s (%d changes)", snapshot.id, company.id, len(changes)
            )
            return RefreshResult(company, snapshot, created=True, changes=changes)

    # --- reading -------------------------------------------------------------------------------

    async def search_local(self, text: str, limit: int = 20) -> list[Company]:
        pattern = like_pattern(search_key(text))
        async with self._sessionmaker() as session:
            rows = await session.scalars(
                select(Company)
                .where(Company.name_search.like(pattern))
                .order_by(Company.name)
                .limit(limit)
            )
            return list(rows)

    async def history(self, company_id: int) -> list[tuple[Snapshot, list[Change]]]:
        async with self._sessionmaker() as session:
            snapshots = list(
                await session.scalars(
                    select(Snapshot)
                    .where(Snapshot.company_id == company_id)
                    .order_by(Snapshot.taken_at.desc(), Snapshot.id.desc())
                )
            )
            changes = list(
                await session.scalars(
                    select(Change).where(Change.company_id == company_id).order_by(Change.id)
                )
            )
        by_snapshot: dict[int, list[Change]] = {}
        for change in changes:
            by_snapshot.setdefault(change.snapshot_id, []).append(change)
        return [(s, by_snapshot.get(s.id, [])) for s in snapshots]

    async def snapshot_pair(
        self, company_id: int, from_id: int | None, to_id: int | None
    ) -> tuple[Snapshot, Snapshot] | None:
        async with self._sessionmaker() as session:
            ordered = list(
                await session.scalars(
                    select(Snapshot)
                    .where(Snapshot.company_id == company_id)
                    .order_by(Snapshot.taken_at, Snapshot.id)
                )
            )
        if not ordered:
            return None
        by_id = {s.id: s for s in ordered}
        to = by_id.get(to_id) if to_id is not None else ordered[-1]
        if to is None:
            return None
        if from_id is not None:
            frm = by_id.get(from_id)
        else:
            index = ordered.index(to)
            frm = ordered[index - 1] if index > 0 else to
        if frm is None:
            return None
        return frm, to

    async def get(self, company_id: int) -> tuple[Company, Snapshot] | None:
        async with self._sessionmaker() as session:
            company = await session.get(Company, company_id)
            if company is None:
                return None
            snapshot = await self.latest_snapshot(session, company_id)
        if snapshot is None:
            return None
        return company, snapshot
