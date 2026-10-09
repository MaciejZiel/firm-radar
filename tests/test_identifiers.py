import pytest

from firm_radar.identifiers import (
    IdKind,
    detect,
    is_valid_nip,
    is_valid_regon,
    normalize_krs,
    search_key,
)

# Checksum-valid numbers generated for tests; they are not meant to point at real entities.
NIP = "1234563218"
REGON9 = "123456785"
REGON14 = "12345678512347"


def test_nip_checksum() -> None:
    assert is_valid_nip(NIP)
    assert not is_valid_nip("1234563219")
    assert not is_valid_nip("12345")
    assert not is_valid_nip("abcdefghij")


def test_regon_checksum() -> None:
    assert is_valid_regon(REGON9)
    assert is_valid_regon(REGON14)
    assert not is_valid_regon("123456789")
    assert not is_valid_regon("1234")


def test_normalize_krs_pads_zeros() -> None:
    assert normalize_krs("19193") == "0000019193"
    with pytest.raises(ValueError, match="KRS"):
        normalize_krs("0")
    with pytest.raises(ValueError, match="KRS"):
        normalize_krs("12345678901")


@pytest.mark.parametrize(
    ("raw", "kind", "value"),
    [
        (NIP, IdKind.NIP, NIP),
        ("PL 123-456-32-18", IdKind.NIP, NIP),
        ("0000019193", IdKind.KRS, "0000019193"),
        ("19193", IdKind.KRS, "0000019193"),
        (REGON9, IdKind.REGON, REGON9),
        ("12345610100000", IdKind.REGON, "123456101"),
        ("krs: 42", IdKind.KRS, "0000000042"),
        (f"nip:{NIP}", IdKind.NIP, NIP),
        (f"REGON:{REGON14}", IdKind.REGON, REGON14),
        ("Przykładowa Spółka", IdKind.NAME, "Przykładowa Spółka"),
    ],
)
def test_detect(raw: str, kind: IdKind, value: str) -> None:
    query = detect(raw)
    assert (query.kind, query.value) == (kind, value)


def test_ten_digits_with_bad_nip_checksum_is_krs() -> None:
    assert detect("1234563219").kind is IdKind.KRS


@pytest.mark.parametrize("raw", ["nip:1234563219", "regon:123", "x", "123456789012345"])
def test_detect_rejects(raw: str) -> None:
    with pytest.raises(ValueError, match=r"\w"):
        detect(raw)


def test_search_key_folds_polish_letters() -> None:
    assert search_key("  ŁÓDZKA   Spółka ") == "lodzka spolka"
