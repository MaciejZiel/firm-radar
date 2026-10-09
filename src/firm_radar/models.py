"""ORM models."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from firm_radar.db import Base


class Company(Base):
    """A company we have resolved at least once. Identifiers are filled as sources reveal them."""

    __tablename__ = "companies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    krs: Mapped[str | None] = mapped_column(String(10), unique=True)
    nip: Mapped[str | None] = mapped_column(String(10), unique=True)
    regon: Mapped[str | None] = mapped_column(String(14), index=True)
    name: Mapped[str] = mapped_column(Text)
    name_search: Mapped[str] = mapped_column(Text, index=True)
    legal_form: Mapped[str | None] = mapped_column(Text)
    city: Mapped[str | None] = mapped_column(Text)
    tracked: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    snapshots: Mapped[list[Snapshot]] = relationship(
        back_populates="company", order_by="Snapshot.taken_at", cascade="all, delete-orphan"
    )


class Snapshot(Base):
    """Normalized profile as seen at ``taken_at``; a row is written only when content changes."""

    __tablename__ = "snapshots"
    __table_args__ = (Index("ix_snapshots_company_taken", "company_id", "taken_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"))
    taken_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    content_hash: Mapped[str] = mapped_column(String(64))
    data: Mapped[dict[str, Any]] = mapped_column(JSONB)

    company: Mapped[Company] = relationship(back_populates="snapshots")
    changes: Mapped[list[Change]] = relationship(
        back_populates="snapshot", cascade="all, delete-orphan"
    )


class Change(Base):
    """One field-level difference between a snapshot and its predecessor."""

    __tablename__ = "changes"
    __table_args__ = (Index("ix_changes_company_detected", "company_id", "detected_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"))
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("snapshots.id", ondelete="CASCADE"))
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    field: Mapped[str] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(16))  # added | removed | modified
    old_value: Mapped[Any] = mapped_column(JSONB, nullable=True)
    new_value: Mapped[Any] = mapped_column(JSONB, nullable=True)

    snapshot: Mapped[Snapshot] = relationship(back_populates="changes")


class SourceCache(Base):
    """Raw upstream responses with a TTL, so repeated lookups do not hit official APIs."""

    __tablename__ = "source_cache"
    __table_args__ = (UniqueConstraint("source", "key", name="uq_source_cache_source_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String(32))
    key: Mapped[str] = mapped_column(Text)
    status: Mapped[int] = mapped_column(Integer)
    payload: Mapped[Any] = mapped_column(JSONB, nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class SourceStatus(Base):
    """Per-source, per-day counters used for health reporting and quota guarding."""

    __tablename__ = "source_status"
    __table_args__ = (UniqueConstraint("source", "day", name="uq_source_status_source_day"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String(32))
    day: Mapped[date] = mapped_column(Date)
    requests: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    errors: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    last_ok_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)


class ProcurementAward(Base):
    """A contractor named in a BZP contract award notice ("ogłoszenie o wyniku postępowania")."""

    __tablename__ = "procurement_awards"
    __table_args__ = (
        UniqueConstraint("notice_id", "contractor_nip", name="uq_procurement_awards_notice_nip"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    notice_id: Mapped[str] = mapped_column(String(64))
    bzp_number: Mapped[str] = mapped_column(String(64))
    tender_id: Mapped[str | None] = mapped_column(String(128))
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    order_type: Mapped[str | None] = mapped_column(String(32))
    order_object: Mapped[str] = mapped_column(Text)
    cpv: Mapped[str | None] = mapped_column(Text)
    buyer_name: Mapped[str] = mapped_column(Text)
    buyer_nip: Mapped[str | None] = mapped_column(String(10))
    buyer_city: Mapped[str | None] = mapped_column(Text)
    contractor_nip: Mapped[str] = mapped_column(String(10), index=True)
    contractor_name: Mapped[str] = mapped_column(Text)
    contractor_city: Mapped[str | None] = mapped_column(Text)
    parts_won: Mapped[int] = mapped_column(Integer, default=1, server_default="1")


class BzpIngestDay(Base):
    """Marks a publication day of BZP notices as fully ingested."""

    __tablename__ = "bzp_ingest_days"

    day: Mapped[date] = mapped_column(Date, primary_key=True)
    notices: Mapped[int] = mapped_column(Integer)
    awards: Mapped[int] = mapped_column(Integer)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
