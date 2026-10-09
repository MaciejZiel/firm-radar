"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-10-10 01:02:30.536376
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "bzp_ingest_days",
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("notices", sa.Integer(), nullable=False),
        sa.Column("awards", sa.Integer(), nullable=False),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("day", name=op.f("pk_bzp_ingest_days")),
    )
    op.create_table(
        "companies",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("krs", sa.String(length=10), nullable=True),
        sa.Column("nip", sa.String(length=10), nullable=True),
        sa.Column("regon", sa.String(length=14), nullable=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("name_search", sa.Text(), nullable=False),
        sa.Column("legal_form", sa.Text(), nullable=True),
        sa.Column("city", sa.Text(), nullable=True),
        sa.Column("tracked", sa.Boolean(), server_default="true", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_companies")),
        sa.UniqueConstraint("krs", name=op.f("uq_companies_krs")),
        sa.UniqueConstraint("nip", name=op.f("uq_companies_nip")),
    )
    op.create_index(op.f("ix_companies_name_search"), "companies", ["name_search"], unique=False)
    op.create_index(op.f("ix_companies_regon"), "companies", ["regon"], unique=False)
    op.create_table(
        "procurement_awards",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("notice_id", sa.String(length=64), nullable=False),
        sa.Column("bzp_number", sa.String(length=64), nullable=False),
        sa.Column("tender_id", sa.String(length=128), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("order_type", sa.String(length=32), nullable=True),
        sa.Column("order_object", sa.Text(), nullable=False),
        sa.Column("cpv", sa.Text(), nullable=True),
        sa.Column("buyer_name", sa.Text(), nullable=False),
        sa.Column("buyer_nip", sa.String(length=10), nullable=True),
        sa.Column("buyer_city", sa.Text(), nullable=True),
        sa.Column("contractor_nip", sa.String(length=10), nullable=False),
        sa.Column("contractor_name", sa.Text(), nullable=False),
        sa.Column("contractor_city", sa.Text(), nullable=True),
        sa.Column("parts_won", sa.Integer(), server_default="1", nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_procurement_awards")),
        sa.UniqueConstraint("notice_id", "contractor_nip", name="uq_procurement_awards_notice_nip"),
    )
    op.create_index(
        op.f("ix_procurement_awards_contractor_nip"),
        "procurement_awards",
        ["contractor_nip"],
        unique=False,
    )
    op.create_index(
        op.f("ix_procurement_awards_published_at"),
        "procurement_awards",
        ["published_at"],
        unique=False,
    )
    op.create_table(
        "source_cache",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("status", sa.Integer(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_source_cache")),
        sa.UniqueConstraint("source", "key", name="uq_source_cache_source_key"),
    )
    op.create_index(
        op.f("ix_source_cache_expires_at"), "source_cache", ["expires_at"], unique=False
    )
    op.create_table(
        "source_status",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("requests", sa.Integer(), server_default="0", nullable=False),
        sa.Column("errors", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_ok_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_source_status")),
        sa.UniqueConstraint("source", "day", name="uq_source_status_source_day"),
    )
    op.create_table(
        "snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("taken_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
            name=op.f("fk_snapshots_company_id_companies"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_snapshots")),
    )
    op.create_index(
        "ix_snapshots_company_taken", "snapshots", ["company_id", "taken_at"], unique=False
    )
    op.create_table(
        "changes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("snapshot_id", sa.Integer(), nullable=False),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("field", sa.String(length=64), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("old_value", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("new_value", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
            name=op.f("fk_changes_company_id_companies"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["snapshot_id"],
            ["snapshots.id"],
            name=op.f("fk_changes_snapshot_id_snapshots"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_changes")),
    )
    op.create_index(
        "ix_changes_company_detected", "changes", ["company_id", "detected_at"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_changes_company_detected", table_name="changes")
    op.drop_table("changes")
    op.drop_index("ix_snapshots_company_taken", table_name="snapshots")
    op.drop_table("snapshots")
    op.drop_table("source_status")
    op.drop_index(op.f("ix_source_cache_expires_at"), table_name="source_cache")
    op.drop_table("source_cache")
    op.drop_index(op.f("ix_procurement_awards_published_at"), table_name="procurement_awards")
    op.drop_index(op.f("ix_procurement_awards_contractor_nip"), table_name="procurement_awards")
    op.drop_table("procurement_awards")
    op.drop_index(op.f("ix_companies_regon"), table_name="companies")
    op.drop_index(op.f("ix_companies_name_search"), table_name="companies")
    op.drop_table("companies")
    op.drop_table("bzp_ingest_days")
