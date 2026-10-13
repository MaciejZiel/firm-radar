"""Client for the VAT taxpayer register ("biała lista") API of the Ministry of Finance.

Docs: https://www.gov.pl/web/kas/api-wykazu-podatnikow-vat - public, no credentials.
The ``search`` methods are limited to 100 queries per day (max 30 subjects each); exceeding
the limit blocks the client until midnight, so calls are cached for 24h and guarded by a
configurable daily budget.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from firm_radar.config import Settings
from firm_radar.schemas import VatData
from firm_radar.sources.base import (
    BadRequest,
    HttpFetcher,
    QuotaExceeded,
    SourceName,
    SourceUnavailable,
    today,
)


@dataclass(frozen=True, slots=True)
class VatLookup:
    data: VatData | None  # None = not present in the register
    fetched_at: datetime
    from_cache: bool
    url: str


class WhiteListClient:
    source = SourceName.WHITELIST

    def __init__(self, fetcher: HttpFetcher, settings: Settings) -> None:
        self._fetcher = fetcher
        self._base = settings.whitelist_base_url.rstrip("/")
        self._ttl = timedelta(seconds=settings.whitelist_cache_ttl_s)
        self._budget = settings.whitelist_daily_budget

    def search_url(self, kind: str, value: str, on: date | None = None) -> str:
        return f"{self._base}/search/{kind}/{value}?date={(on or today()).isoformat()}"

    async def by_nip(self, nip: str) -> VatLookup:
        return await self._search("nip", nip)

    async def by_regon(self, regon: str) -> VatLookup:
        return await self._search("regon", regon)

    async def _search(self, kind: str, value: str) -> VatLookup:
        on = today()
        key = f"search/{kind}/{value}"
        url = self.search_url(kind, value, on)
        cached = await self._fetcher.store.cache_get(self.source, key)
        if cached is not None:
            return VatLookup(parse_vat(cached.payload), cached.fetched_at, True, url)

        if await self._fetcher.store.requests_today(self.source) >= self._budget:
            raise QuotaExceeded(
                self.source, f"daily budget of {self._budget} white list queries used up"
            )
        result = await self._fetcher.get_json(
            self.source, f"{self._base}/search/{kind}/{value}", {"date": on.isoformat()}
        )
        if result.status == 400:
            message = (result.payload or {}).get("message") if result.payload else None
            raise BadRequest(self.source, message or f"rejected {kind} {value}")
        if result.status != 200 or not isinstance(result.payload, dict):
            raise SourceUnavailable(self.source, f"HTTP {result.status}")
        fetched_at = await self._fetcher.store.cache_put(
            self.source, key, 200, result.payload, self._ttl
        )
        return VatLookup(parse_vat(result.payload), fetched_at, False, url)


def _date(value: Any) -> date | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def parse_vat(payload: Any) -> VatData | None:
    result = (payload or {}).get("result") or {}
    subject = result.get("subject")
    if not subject and result.get("subjects"):
        subject = result["subjects"][0]
    if not isinstance(subject, dict) or not subject.get("nip"):
        return None
    return VatData(
        name=str(subject.get("name") or "?"),
        nip=str(subject["nip"]),
        status=subject.get("statusVat"),
        regon=subject.get("regon") or None,
        krs=subject.get("krs") or None,
        working_address=subject.get("workingAddress") or None,
        residence_address=subject.get("residenceAddress") or None,
        registered_on=_date(subject.get("registrationLegalDate")),
        removed_on=_date(subject.get("removalDate")),
        removal_basis=subject.get("removalBasis") or None,
        restored_on=_date(subject.get("restorationDate")),
        denied_on=_date(subject.get("registrationDenialDate")),
        account_numbers=sorted(str(a) for a in subject.get("accountNumbers") or []),
        has_virtual_accounts=subject.get("hasVirtualAccounts"),
    )
