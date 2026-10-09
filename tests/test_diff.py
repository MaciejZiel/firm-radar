from __future__ import annotations

from firm_radar.schemas import CompanyData, Identifiers, VatData
from firm_radar.services.diff import VAT_NOT_REGISTERED, FieldChange, diff, diff_flat, flatten
from firm_radar.services.profiles import Collected, merge
from firm_radar.sources.krs import parse_extract
from tests import cassettes


def _company(version: str, vat: VatData | None = None) -> CompanyData:
    krs = parse_extract(cassettes.load(f"krs_odpis_0000999901_{version}.json"))
    return merge(Collected(krs=krs, vat=vat, vat_checked=True))


def test_no_changes_for_identical_data() -> None:
    assert diff(_company("v1"), _company("v1")) == []


def test_board_address_and_capital_changes() -> None:
    changes = diff(_company("v1"), _company("v2"))
    assert FieldChange("management", "added", new="CZŁONEK ZARZĄDU: A*** N****") in changes
    assert (
        FieldChange(
            "address",
            "modified",
            old="UL. PRZYKŁADOWA 1/2, 00-001 TESTOWO",
            new="UL. ZMYŚLONA 10, 00-001 TESTOWO",
        )
        in changes
    )
    assert (
        FieldChange("share_capital", "modified", old="5000.00 PLN", new="50000.00 PLN") in changes
    )
    assert FieldChange(
        "krs_last_entry", "modified", old="7 (2026-08-20)", new="8 (2026-10-05)"
    ) in (changes)


def test_vat_status_change() -> None:
    active = VatData(name="X", nip="1234563218", status="Czynny", account_numbers=["1", "2"])
    removed = VatData(name="X", nip="1234563218", status=None, account_numbers=[])
    changes = diff(_company("v1", active), _company("v1", removed))
    assert FieldChange("vat_status", "modified", old="Czynny", new="REMOVED") in changes
    assert {c.old for c in changes if c.field == "vat_accounts"} == {"1", "2"}


def test_not_registered_for_vat() -> None:
    data = _company("v1", None)
    assert flatten(data)["vat_status"] == VAT_NOT_REGISTERED


def test_list_fields_compare_as_sets() -> None:
    old = {"management": ["A", "B"]}
    new = {"management": ["B", "A", "C"]}
    assert diff_flat(old, new) == [FieldChange("management", "added", new="C")]


def test_scalar_added_and_removed() -> None:
    assert diff_flat({"website": None}, {"website": "x"}) == [
        FieldChange("website", "added", new="x")
    ]
    assert diff_flat({"website": "x"}, {}) == [FieldChange("website", "removed", old="x")]


def test_merge_prefers_krs_and_fills_ids_from_vat() -> None:
    vat = VatData(name="VAT NAME", nip="1234563218", regon="123456785", krs="0000999901")
    data = merge(Collected(vat=vat, vat_checked=True))
    assert data.name == "VAT NAME"
    assert data.identifiers == Identifiers(krs="0000999901", nip="1234563218", regon="123456785")
