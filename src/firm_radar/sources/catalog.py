"""Human-readable facts about each registry: where it lives, its terms and its limits."""

from __future__ import annotations

from dataclasses import dataclass

from firm_radar.sources.base import SourceName


@dataclass(frozen=True, slots=True)
class SourceInfo:
    name: SourceName
    label: str
    publisher: str
    homepage: str
    docs_url: str
    terms: str
    limits: str


CATALOG: dict[SourceName, SourceInfo] = {
    SourceName.KRS: SourceInfo(
        name=SourceName.KRS,
        label="KRS – Krajowy Rejestr Sądowy",
        publisher="Ministerstwo Sprawiedliwości",
        homepage="https://prs.ms.gov.pl/krs/openApi",
        docs_url="https://prs.ms.gov.pl/krs/openApi",
        terms=(
            "Open API published under art. 4b of the KRS Act and art. 24(1) of the Act on open "
            "data and reuse of public sector information; no registration, personal data masked "
            "by the publisher."
        ),
        limits="No published rate limit; responses cached for 12 h.",
    ),
    SourceName.WHITELIST: SourceInfo(
        name=SourceName.WHITELIST,
        label="Biała lista podatników VAT",
        publisher="Ministerstwo Finansów / KAS",
        homepage="https://www.podatki.gov.pl/wykaz-podatnikow-vat-wyszukiwarka",
        docs_url="https://www.gov.pl/web/kas/api-wykazu-podatnikow-vat",
        terms=(
            "Public register (art. 96b of the VAT Act) with a public API; no registration. "
            "Data is informational - the register itself is the authoritative source."
        ),
        limits=(
            "search: 100 queries/day (max 30 subjects each); exceeding it blocks access until "
            "midnight. Responses cached for 24 h and capped by a daily budget."
        ),
    ),
    SourceName.BZP: SourceInfo(
        name=SourceName.BZP,
        label="BZP – Biuletyn Zamówień Publicznych",
        publisher="Urząd Zamówień Publicznych (platforma e-Zamówienia)",
        homepage="https://ezamowienia.gov.pl/mo-client-board/bzp/list",
        docs_url="https://ezamowienia.gov.pl/pl/regulamin/",
        terms=(
            "API BZP (WebService) for reading published notices is free and needs no access "
            "request (Regulamin korzystania z API, e-Zamówienia)."
        ),
        limits="Max 500 notices per page; ingested once per day for recent days only.",
    ),
}
