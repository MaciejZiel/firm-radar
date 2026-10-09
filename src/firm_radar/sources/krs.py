"""Client for the open KRS API of the Ministry of Justice (https://prs.ms.gov.pl/krs/openApi).

Public, free, no credentials. Personal data in extracts is masked by the publisher.
Legal basis for reuse: art. 4b of the KRS Act together with art. 24(1) of the Act of
11 August 2021 on open data and the reuse of public sector information.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Literal

from firm_radar.config import Settings
from firm_radar.identifiers import normalize_regon
from firm_radar.schemas import Activity, Address, Body, KrsData, Money, Person
from firm_radar.sources.base import BadRequest, HttpFetcher, SourceName

Register = Literal["P", "S"]


@dataclass(frozen=True, slots=True)
class KrsExtract:
    data: KrsData
    fetched_at: datetime
    from_cache: bool
    url: str


class KrsClient:
    source = SourceName.KRS

    def __init__(self, fetcher: HttpFetcher, settings: Settings) -> None:
        self._fetcher = fetcher
        self._base = settings.krs_base_url.rstrip("/")
        self._ttl = timedelta(seconds=settings.krs_cache_ttl_s)

    def extract_url(self, krs: str, register: Register = "P") -> str:
        return f"{self._base}/OdpisAktualny/{krs}?rejestr={register}&format=json"

    async def current_extract(self, krs: str) -> KrsExtract | None:
        """Current extract ("odpis aktualny"); tries the business register, then associations."""
        for register in ("P", "S"):
            key = f"OdpisAktualny/{register}/{krs}"
            cached = await self._fetcher.store.cache_get(self.source, key)
            if cached is not None:
                status, payload, fetched_at, from_cache = (
                    cached.status,
                    cached.payload,
                    cached.fetched_at,
                    True,
                )
            else:
                result = await self._fetcher.get_json(
                    self.source,
                    f"{self._base}/OdpisAktualny/{krs}",
                    {"rejestr": register, "format": "json"},
                )
                if result.status not in (200, 404):
                    raise BadRequest(self.source, f"HTTP {result.status} for KRS {krs}")
                status, payload = result.status, result.payload
                fetched_at = await self._fetcher.store.cache_put(
                    self.source, key, status, payload, self._ttl
                )
                from_cache = False
            if status == 200 and payload:
                return KrsExtract(
                    parse_extract(payload, register),
                    fetched_at,
                    from_cache,
                    self.extract_url(krs, register),
                )
        return None

    async def daily_bulletin(self, day: date) -> list[str]:
        """KRS numbers (zero-padded) with any registry entry on ``day``."""
        key = f"Biuletyn/{day.isoformat()}"
        cached = await self._fetcher.store.cache_get(self.source, key)
        if cached is not None:
            payload = cached.payload
        else:
            base = self._base.removesuffix("/krs").removesuffix("/Krs")
            result = await self._fetcher.get_json(
                self.source, f"{base}/Krs/Biuletyn/{day.isoformat()}"
            )
            if result.status == 404:
                payload = []
            elif result.status != 200:
                raise BadRequest(self.source, f"HTTP {result.status} for bulletin {day}")
            else:
                payload = result.payload or []
            # A past day's bulletin no longer changes; keep it for a week.
            await self._fetcher.store.cache_put(self.source, key, 200, payload, timedelta(days=7))
        return sorted({str(n).zfill(10) for n in payload if str(n).isdigit()})


# --- parsing -----------------------------------------------------------------------------------


def _date(value: Any) -> date | None:
    if not isinstance(value, str) or not value:
        return None
    for fmt in ("%d.%m.%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


def _money(node: Any) -> Money | None:
    if not isinstance(node, dict) or not node.get("wartosc"):
        return None
    amount = str(node["wartosc"]).replace(" ", "").replace(",", ".")
    return Money(amount=amount, currency=str(node.get("waluta") or "PLN"))


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    text = re.sub(r"\s+", " ", str(value)).strip()
    return text or None


def _person(node: dict[str, Any], role_key: str = "funkcjaWOrganie") -> Person:
    if node.get("nazwa"):  # legal person sitting on a body
        name = str(node["nazwa"])
    else:
        first = node.get("imiona") or {}
        last = node.get("nazwisko") or {}
        parts = [
            first.get("imie"),
            first.get("imieDrugie"),
            last.get("nazwiskoICzlon"),
            last.get("nazwiskoCzesc2"),
        ]
        name = " ".join(p for p in parts if p) or "?"
    return Person(
        name=name,
        role=_clean(node.get(role_key)),
        suspended=bool(node.get("czyZawieszona", False)),
    )


def _activities(items: Any) -> list[Activity]:
    out: list[Activity] = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        code = ".".join(p for p in (item.get("kodDzial"), item.get("kodKlasa")) if p) + (
            f".{item['kodPodklasa']}" if item.get("kodPodklasa") else ""
        )
        if code:
            out.append(Activity(code=code, description=_clean(item.get("opis")) or ""))
    return out


def parse_extract(payload: dict[str, Any], register: Register = "P") -> KrsData:
    odpis = payload.get("odpis") or {}
    header = odpis.get("naglowekA") or {}
    sections = odpis.get("dane") or {}
    d1 = sections.get("dzial1") or {}
    d2 = sections.get("dzial2") or {}
    d3 = sections.get("dzial3") or {}

    entity = d1.get("danePodmiotu") or {}
    ids = entity.get("identyfikatory") or {}
    seat = d1.get("siedzibaIAdres") or {}
    addr = seat.get("adres") or {}

    management: Body | None = None
    rep = d2.get("reprezentacja")
    if isinstance(rep, dict):
        management = Body(
            name=_clean(rep.get("nazwaOrganu")),
            representation_rule=_clean(rep.get("sposobReprezentacji")),
            members=[_person(m) for m in rep.get("sklad") or [] if isinstance(m, dict)],
        )

    boards = [
        Body(
            name=_clean(b.get("nazwa")),
            members=[_person(m) for m in b.get("sklad") or [] if isinstance(m, dict)],
        )
        for b in d2.get("organNadzoru") or []
        if isinstance(b, dict)
    ]
    proxies = [
        _person(p, role_key="rodzajProkury")
        for p in d2.get("prokurenci") or []
        if isinstance(p, dict)
    ]
    activity = d3.get("przedmiotDzialalnosci") or {}
    regon = str(ids["regon"]) if ids.get("regon") else None

    deregistered = next(
        (_date(v) for k, v in header.items() if "wykresl" in k.lower() and _date(v)), None
    )

    return KrsData(
        krs=str(header.get("numerKRS") or "").zfill(10),
        registry=register,
        name=_clean(entity.get("nazwa")) or "?",
        legal_form=_clean(entity.get("formaPrawna")),
        nip=str(ids["nip"]) if ids.get("nip") else None,
        regon=normalize_regon(regon) if regon else None,
        registered_on=_date(header.get("dataRejestracjiWKRS")),
        last_entry_no=header.get("numerOstatniegoWpisu"),
        last_entry_on=_date(header.get("dataOstatniegoWpisu")),
        deregistered_on=deregistered,
        address=Address(
            street=_clean(addr.get("ulica")),
            building=_clean(addr.get("nrDomu")),
            unit=_clean(addr.get("nrLokalu")),
            postal_code=_clean(addr.get("kodPocztowy")),
            city=_clean(addr.get("miejscowosc")),
            country=_clean(addr.get("kraj")),
        )
        if addr
        else None,
        website=_clean(seat.get("adresStronyInternetowej")),
        email=_clean(seat.get("adresPocztyElektronicznej")),
        share_capital=_money((d1.get("kapital") or {}).get("wysokoscKapitaluZakladowego")),
        management=management,
        supervisory_boards=boards,
        proxies=proxies,
        main_activity=_activities(activity.get("przedmiotPrzewazajacejDzialalnosci")),
        other_activities=_activities(activity.get("przedmiotPozostalejDzialalnosci")),
    )
