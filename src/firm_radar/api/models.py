"""Response models of the public JSON API (with OpenAPI examples; all example data is fictional)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.config import JsonDict

from firm_radar.models import Change, Company, Snapshot
from firm_radar.schemas import CompanyData, SourceRef
from firm_radar.services.diff import FieldChange

EXAMPLE_COMPANY: JsonDict = {
    "id": 1,
    "name": "PRZYKŁADOWA SPÓŁKA TESTOWA SP. Z O.O.",
    "krs": "0000999901",
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


class ProfileOut(BaseModel):
    company: CompanySummary
    snapshot_id: int
    snapshot_taken_at: datetime
    data: CompanyData
    sources: list[SourceRef]

    @classmethod
    def of(cls, company: Company, snapshot: Snapshot) -> ProfileOut:
        return cls(
            company=CompanySummary.of(company),
            snapshot_id=snapshot.id,
            snapshot_taken_at=snapshot.taken_at,
            data=CompanyData.model_validate(snapshot.data),
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


class ErrorOut(BaseModel):
    detail: str
