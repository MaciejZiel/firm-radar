"""Field-level comparison of two company snapshots.

Only fields that matter to a reader are tracked (name, seat, board, VAT status, ...). List
fields are compared as sets so that, e.g., a new board member shows up as one ``added`` change
rather than a rewrite of the whole list.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from firm_radar.schemas import Body, CompanyData

ChangeKind = Literal["added", "removed", "modified"]

VAT_NOT_REGISTERED = "NOT_REGISTERED"


@dataclass(frozen=True, slots=True)
class FieldChange:
    field: str
    kind: ChangeKind
    old: Any = None
    new: Any = None


def _members(body: Body | None) -> list[str]:
    return [m.label() for m in body.members] if body else []


def _vat_status(data: CompanyData) -> str | None:
    if data.vat is not None:
        return data.vat.status or "REMOVED"
    if data.vat_registered is False:
        return VAT_NOT_REGISTERED
    return None


Extractor = Callable[[CompanyData], Any]

TRACKED: dict[str, Extractor] = {
    "name": lambda d: d.name,
    "legal_form": lambda d: d.legal_form,
    "address": lambda d: d.address,
    "website": lambda d: d.krs.website if d.krs else None,
    "share_capital": lambda d: (
        f"{d.krs.share_capital.amount} {d.krs.share_capital.currency}"
        if d.krs and d.krs.share_capital
        else None
    ),
    "krs_last_entry": lambda d: (
        f"{d.krs.last_entry_no} ({d.krs.last_entry_on.isoformat()})"
        if d.krs and d.krs.last_entry_no and d.krs.last_entry_on
        else None
    ),
    "krs_deregistered_on": lambda d: (
        d.krs.deregistered_on.isoformat() if d.krs and d.krs.deregistered_on else None
    ),
    "representation_rule": lambda d: (
        d.krs.management.representation_rule if d.krs and d.krs.management else None
    ),
    "management": lambda d: _members(d.krs.management) if d.krs else [],
    "supervisory_board": lambda d: (
        [m for b in d.krs.supervisory_boards for m in _members(b)] if d.krs else []
    ),
    "proxies": lambda d: [p.label() for p in d.krs.proxies] if d.krs else [],
    "main_activity": lambda d: (
        [f"{a.code} {a.description}" for a in d.krs.main_activity] if d.krs else []
    ),
    "vat_status": _vat_status,
    "vat_accounts": lambda d: list(d.vat.account_numbers) if d.vat else [],
    "vat_working_address": lambda d: d.vat.working_address if d.vat else None,
}


def flatten(data: CompanyData) -> dict[str, Any]:
    return {key: extract(data) for key, extract in TRACKED.items()}


def diff(old: CompanyData, new: CompanyData) -> list[FieldChange]:
    return diff_flat(flatten(old), flatten(new))


def diff_flat(old: dict[str, Any], new: dict[str, Any]) -> list[FieldChange]:
    changes: list[FieldChange] = []
    for key in TRACKED:
        before, after = old.get(key), new.get(key)
        if isinstance(before, list) or isinstance(after, list):
            before_set, after_set = set(before or []), set(after or [])
            changes.extend(
                FieldChange(key, "removed", old=v) for v in sorted(before_set - after_set)
            )
            changes.extend(FieldChange(key, "added", new=v) for v in sorted(after_set - before_set))
        elif before != after:
            if before is None:
                changes.append(FieldChange(key, "added", new=after))
            elif after is None:
                changes.append(FieldChange(key, "removed", old=before))
            else:
                changes.append(FieldChange(key, "modified", old=before, new=after))
    return changes
