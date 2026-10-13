"""Response models of the public JSON API (with OpenAPI examples; all example data is fictional)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.config import JsonDict

from firm_radar.models import Change, Company, ProcurementAward, Snapshot
from firm_radar.schemas import CompanyData, SourceRef
from firm_radar.services.diff import FieldChange
from firm_radar.services.procurement import AwardSummary
from firm_radar.sources.bzp import NOTICE_PDF_URL

EXAMPLE_COMPANY: JsonDict = {
    "id": 1,
    "name": "PRZYKŁADOWA SPÓŁKA TESTOWA SP. Z O.O.",
    "krs": "0009999901",
    "nip": "1234563218",
    "regon": "123456785",
    "legal_form": "SPÓŁKA Z OGRANICZONĄ ODPOWIEDZIALNOŚCIĄ",
    "city": "TESTOWO",
    "last_checked_at": "2026-10-05T08:00:00Z",
}


class CompanySummary(BaseModel):
    model_config = ConfigDict(json_schema_extra={"example": EXAMPLE_COMPANY})

    id: int
    name: str
    krs: str | None
    nip: str | None
    regon: str | None
    legal_form: str | None
    city: str | None
    last_checked_at: datetime | None

    @classmethod
    def of(cls, c: Company) -> CompanySummary:
        return cls(
            id=c.id,
            name=c.name,
            krs=c.krs,
            nip=c.nip,
            regon=c.regon,
            legal_form=c.legal_form,
            city=c.city,
            last_checked_at=c.last_checked_at,
        )


class CandidateOut(BaseModel):
    """A contractor seen in BZP award notices but not looked up yet; open it by NIP."""

    name: str
    nip: str
    awards: int
    source: Literal["bzp"] = "bzp"


class SearchOut(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "query": "1234563218",
                "kind": "nip",
                "value": "1234563218",
                "results": [EXAMPLE_COMPANY],
                "note": None,
            }
        }
    )

    query: str
    kind: Literal["krs", "nip", "regon", "name"]
    value: str
    results: list[CompanySummary]
    candidates: list[CandidateOut] = Field(
        default_factory=list, description="Name matches among BZP contractors (name search only)"
    )
    note: str | None = Field(default=None, description="Why the result may be incomplete")


class ChangeOut(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "field": "management",
                "kind": "added",
                "old": None,
                "new": "CZŁONEK ZARZĄDU: A*** N****",
            }
        }
    )

    field: str
    kind: Literal["added", "removed", "modified"]
    old: Any = None
    new: Any = None

    @classmethod
    def of(cls, c: Change | FieldChange) -> ChangeOut:
        if isinstance(c, Change):
            return cls(field=c.field, kind=c.kind, old=c.old_value, new=c.new_value)
        return cls(field=c.field, kind=c.kind, old=c.old, new=c.new)


class AwardOut(BaseModel):
    bzp_number: str
    published_at: datetime
    order_object: str
    order_type: str | None
    buyer_name: str
    buyer_city: str | None
    lots_won: int
    notice_url: str

    @classmethod
    def of(cls, a: ProcurementAward) -> AwardOut:
        return cls(
            bzp_number=a.bzp_number,
            published_at=a.published_at,
            order_object=a.order_object,
            order_type=a.order_type,
            buyer_name=a.buyer_name,
            buyer_city=a.buyer_city,
            lots_won=a.parts_won,
            notice_url=NOTICE_PDF_URL.format(a.notice_id),
        )


class ProcurementOut(BaseModel):
    total_awards: int = Field(description="Award notices naming this NIP as a contractor")
    total_lots: int
    coverage_from: date | None = Field(description="First ingested BZP publication day")
    coverage_to: date | None
    coverage_days: int
    recent: list[AwardOut]

    @classmethod
    def of(cls, s: AwardSummary) -> ProcurementOut:
        return cls(
            total_awards=s.total_awards,
            total_lots=s.total_lots,
            coverage_from=s.coverage_from,
            coverage_to=s.coverage_to,
            coverage_days=s.coverage_days,
            recent=[AwardOut.of(a) for a in s.recent],
        )


class ProfileOut(BaseModel):
    company: CompanySummary
    snapshot_id: int
    snapshot_taken_at: datetime
    data: CompanyData
    procurement: ProcurementOut | None = Field(
        default=None, description="Public procurement awards; null when the NIP is unknown"
    )
    sources: list[SourceRef]

    @classmethod
    def of(
        cls, company: Company, snapshot: Snapshot, awards: AwardSummary | None = None
    ) -> ProfileOut:
        return cls(
            company=CompanySummary.of(company),
            snapshot_id=snapshot.id,
            snapshot_taken_at=snapshot.taken_at,
            data=CompanyData.model_validate(snapshot.data),
            procurement=ProcurementOut.of(awards) if awards else None,
            sources=[SourceRef.model_validate(r) for r in company.source_refs or []],
        )


class RefreshOut(BaseModel):
    company_id: int
    snapshot_id: int
    new_snapshot: bool = Field(description="False when nothing changed since the last snapshot")
    changes: list[ChangeOut]


class TimelineEntry(BaseModel):
    snapshot_id: int
    taken_at: datetime
    changes: list[ChangeOut]


class HistoryOut(BaseModel):
    company_id: int
    snapshots: int
    timeline: list[TimelineEntry] = Field(description="Newest first")


class DiffOut(BaseModel):
    company_id: int
    from_snapshot: int
    to_snapshot: int
    from_taken_at: datetime
    to_taken_at: datetime
    changes: list[ChangeOut]


class SourceHealthOut(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "source": "whitelist",
                "label": "Biała lista podatników VAT",
                "status": "ok",
                "docs_url": "https://www.gov.pl/web/kas/api-wykazu-podatnikow-vat",
                "terms": "Public register with a public API; no registration.",
                "limits": "search: 100 queries/day",
                "requests_today": 12,
                "errors_today": 0,
                "last_ok_at": "2026-10-05T08:00:00Z",
                "last_error_at": None,
                "last_error": None,
                "cached_responses": 40,
                "daily_budget": 80,
                "budget_left": 68,
            }
        }
    )

    source: str
    label: str
    status: Literal["ok", "degraded", "down", "unknown"]
    docs_url: str
    terms: str
    limits: str
    requests_today: int
    errors_today: int
    last_ok_at: datetime | None
    last_error_at: datetime | None
    last_error: str | None
    cached_responses: int
    daily_budget: int | None = None
    budget_left: int | None = None


class BzpCoverageOut(BaseModel):
    days: int
    first_day: date | None
    last_day: date | None
    awards: int


class HealthOut(BaseModel):
    sources: list[SourceHealthOut]
    bzp_coverage: BzpCoverageOut
    scheduler_enabled: bool


class ErrorOut(BaseModel):
    detail: str
