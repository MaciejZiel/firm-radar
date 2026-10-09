"""Normalized company model shared by sources, snapshots and the API."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Model(BaseModel):
    model_config = ConfigDict(frozen=True)


class Address(Model):
    street: str | None = None
    building: str | None = None
    unit: str | None = None
    postal_code: str | None = None
    city: str | None = None
    country: str | None = None

    def one_line(self) -> str:
        street = " ".join(p for p in (self.street, self.building) if p)
        if street and self.unit:
            street = f"{street}/{self.unit}"
        city = " ".join(p for p in (self.postal_code, self.city) if p)
        return ", ".join(p for p in (street, city) if p)


class Money(Model):
    amount: str = Field(description="Decimal amount as published, e.g. '5000.00'")
    currency: str = "PLN"


class Person(Model):
    """A board member as published by the open KRS API (surnames and first names are masked)."""

    name: str
    role: str | None = None
    suspended: bool = False

    def label(self) -> str:
        return f"{self.role}: {self.name}" if self.role else self.name


class Body(Model):
    name: str | None = None
    representation_rule: str | None = None
    members: list[Person] = Field(default_factory=list)


class Activity(Model):
    code: str
    description: str


class KrsData(Model):
    krs: str
    registry: Literal["P", "S"] = Field(description="P = business register, S = associations")
    name: str
    legal_form: str | None = None
    nip: str | None = None
    regon: str | None = None
    registered_on: date | None = None
    last_entry_no: int | None = None
    last_entry_on: date | None = None
    deregistered_on: date | None = None
    address: Address | None = None
    website: str | None = None
    email: str | None = None
    share_capital: Money | None = None
    management: Body | None = None
    supervisory_boards: list[Body] = Field(default_factory=list)
    proxies: list[Person] = Field(default_factory=list)
    main_activity: list[Activity] = Field(default_factory=list)
    other_activities: list[Activity] = Field(default_factory=list)


class VatData(Model):
    name: str
    nip: str
    status: str | None = Field(
        default=None, description="'Czynny' (active), 'Zwolniony' (exempt) or null if removed"
    )
    regon: str | None = None
    krs: str | None = None
    working_address: str | None = None
    residence_address: str | None = None
    registered_on: date | None = None
    removed_on: date | None = None
    removal_basis: str | None = None
    restored_on: date | None = None
    denied_on: date | None = None
    account_numbers: list[str] = Field(default_factory=list)
    has_virtual_accounts: bool | None = None


class Identifiers(Model):
    krs: str | None = None
    nip: str | None = None
    regon: str | None = None


class CompanyData(Model):
    """What is stored in a snapshot: the merged view of all registries at one point in time."""

    identifiers: Identifiers
    name: str
    legal_form: str | None = None
    address: str | None = None
    city: str | None = None
    krs: KrsData | None = None
    vat: VatData | None = None
    vat_registered: bool | None = Field(
        default=None, description="False when the white list has no entry for the NIP"
    )


class SourceRef(Model):
    source: str
    label: str
    url: str
    fetched_at: datetime | None = None
    from_cache: bool = False
    ok: bool = True
    note: str | None = None
