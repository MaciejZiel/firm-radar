"""Client for the BZP (Biuletyn Zamówień Publicznych) notice API on the e-Zamówienia platform.

Reading published national notices needs no registration (Regulamin korzystania z API,
§ on API BZP WebService: "W zakresie Webservice nie wymagane jest składanie wniosku
dostępowego"); use is free of charge. The API cannot filter by contractor, so we ingest
contract award notices ("TenderResultNotice") day by day and index contractors locally.
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from typing import Any

from firm_radar.config import Settings
from firm_radar.identifiers import is_valid_nip
from firm_radar.sources.base import HttpFetcher, SourceName, SourceUnavailable

PAGE_SIZE = 500  # maximum accepted by the API
NOTICE_PDF_URL = "https://ezamowienia.gov.pl/mo-board/api/v1/Board/GetNoticePdfById?noticeId={}"


@dataclass(frozen=True, slots=True)
class Award:
    notice_id: str
    bzp_number: str
    tender_id: str | None
    published_at: datetime
    order_type: str | None
    order_object: str
    cpv: str | None
    buyer_name: str
    buyer_nip: str | None
    buyer_city: str | None
    contractor_nip: str
    contractor_name: str
    contractor_city: str | None
    parts_won: int


class BzpClient:
    source = SourceName.BZP

    def __init__(self, fetcher: HttpFetcher, settings: Settings) -> None:
        self._fetcher = fetcher
        self._base = settings.bzp_base_url.rstrip("/")

    async def result_notices(self, day: date) -> AsyncIterator[list[dict[str, Any]]]:
        """Yield pages of contract award notices published on ``day`` (keyset pagination)."""
        start = datetime.combine(day, time.min, tzinfo=UTC)
        end = datetime.combine(day, time(23, 59, 59), tzinfo=UTC)
        search_after: str | None = None
        while True:
            params = {
                "NoticeType": "TenderResultNotice",
                "PublicationDateFrom": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "PublicationDateTo": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "PageSize": str(PAGE_SIZE),
            }
            if search_after:
                params["SearchAfter"] = search_after
            result = await self._fetcher.get_json(self.source, f"{self._base}/notice", params)
            if result.status != 200 or not isinstance(result.payload, list):
                raise SourceUnavailable(self.source, f"HTTP {result.status} listing notices")
            raw = [n for n in result.payload if isinstance(n, dict)]
            # With SearchAfter the API keeps paging past PublicationDateTo, so trim to the day.
            page = [n for n in raw if _published_on(n) == day]
            if page:
                yield page
            if len(raw) < PAGE_SIZE or len(page) < len(raw):
                return
            next_cursor = raw[-1].get("objectId")
            if not next_cursor or next_cursor == search_after:
                return
            search_after = str(next_cursor)


_DIGITS = re.compile(r"\D")


def clean_nip(value: Any) -> str | None:
    if not value:
        return None
    digits = _DIGITS.sub("", str(value))
    return digits if is_valid_nip(digits) else None


def _published(value: Any) -> datetime:
    text = str(value or "")
    match = re.match(r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})", text)
    if not match:
        raise ValueError(f"bad publicationDate {value!r}")
    return datetime.fromisoformat(match.group(1)).replace(tzinfo=UTC)


def _published_on(notice: dict[str, Any]) -> date | None:
    try:
        return _published(notice.get("publicationDate")).date()
    except ValueError:
        return None


def parse_awards(notice: dict[str, Any]) -> list[Award]:
    """One award per distinct contractor NIP; a notice may cover several lots ("części")."""
    notice_id = notice.get("objectId")
    if not notice_id or notice.get("noticeType") != "TenderResultNotice":
        return []
    winners: dict[str, tuple[dict[str, Any], int]] = {}
    for contractor in notice.get("contractors") or []:
        if not isinstance(contractor, dict):
            continue
        nip = clean_nip(contractor.get("contractorNationalId"))
        if nip is None or not contractor.get("contractorName"):
            continue
        first, count = winners.get(nip, (contractor, 0))
        winners[nip] = (first, count + 1)
    if not winners:
        return []
    published_at = _published(notice.get("publicationDate"))
    return [
        Award(
            notice_id=str(notice_id),
            bzp_number=str(notice.get("bzpNumber") or notice.get("noticeNumber") or ""),
            tender_id=notice.get("tenderId"),
            published_at=published_at,
            order_type=notice.get("orderType"),
            order_object=str(notice.get("orderObject") or "").strip(),
            cpv=notice.get("cpvCode"),
            buyer_name=str(notice.get("organizationName") or "").strip(),
            buyer_nip=clean_nip(notice.get("organizationNationalId")),
            buyer_city=notice.get("organizationCity"),
            contractor_nip=nip,
            contractor_name=str(contractor["contractorName"]).strip(),
            contractor_city=contractor.get("contractorCity"),
            parts_won=count,
        )
        for nip, (contractor, count) in winners.items()
    ]
