"""Validation and detection of Polish business identifiers (NIP, REGON, KRS)."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from enum import StrEnum

_NIP_WEIGHTS = (6, 5, 7, 2, 3, 4, 5, 6, 7)
_REGON9_WEIGHTS = (8, 9, 2, 3, 4, 5, 6, 7)
_REGON14_WEIGHTS = (2, 4, 8, 5, 0, 9, 7, 3, 6, 1, 2, 4, 8)
_SEPARATORS = re.compile(r"[\s\-./]")


class IdKind(StrEnum):
    KRS = "krs"
    NIP = "nip"
    REGON = "regon"
    NAME = "name"


@dataclass(frozen=True, slots=True)
class Query:
    kind: IdKind
    value: str


def _checksum(digits: str, weights: tuple[int, ...]) -> int:
    return sum(int(d) * w for d, w in zip(digits, weights, strict=False)) % 11


def is_valid_nip(value: str) -> bool:
    if not (len(value) == 10 and value.isdigit()):
        return False
    control = _checksum(value[:9], _NIP_WEIGHTS)
    return control != 10 and control == int(value[9])


def is_valid_regon(value: str) -> bool:
    if not value.isdigit():
        return False
    if len(value) == 9:
        return _checksum(value[:8], _REGON9_WEIGHTS) % 10 == int(value[8])
    if len(value) == 14:
        control = _checksum(value[:13], _REGON14_WEIGHTS) % 10
        return is_valid_regon(value[:9]) and control == int(value[13])
    return False


def normalize_krs(value: str) -> str:
    digits = _SEPARATORS.sub("", value)
    if not digits.isdigit() or not 1 <= len(digits) <= 10 or int(digits) == 0:
        raise ValueError(f"not a KRS number: {value!r}")
    return digits.zfill(10)


def normalize_regon(value: str) -> str:
    """REGON-14 of a main unit ends in ``00000``; the 9-digit form is what registries match on."""
    if len(value) == 14 and value.endswith("00000"):
        return value[:9]
    return value


def detect(raw: str) -> Query:
    """Guess what the user typed. An explicit ``krs:``/``nip:``/``regon:`` prefix always wins.

    KRS numbers and NIPs are both 10 digits long; a string is treated as a NIP only when its
    checksum is valid and it does not start with ``00`` (KRS numbers are zero-padded and no NIP
    issued so far starts with two zeros).
    """
    text = raw.strip()
    prefix, sep, rest = text.partition(":")
    if sep and prefix.lower() in {k.value for k in IdKind if k is not IdKind.NAME}:
        kind = IdKind(prefix.lower())
        value = _SEPARATORS.sub("", rest)
        if kind is IdKind.NIP:
            value = value.upper().removeprefix("PL")
            if not is_valid_nip(value):
                raise ValueError(f"invalid NIP: {rest.strip()!r}")
            return Query(kind, value)
        if kind is IdKind.REGON:
            if not is_valid_regon(value):
                raise ValueError(f"invalid REGON: {rest.strip()!r}")
            return Query(kind, normalize_regon(value))
        return Query(kind, normalize_krs(value))

    compact = _SEPARATORS.sub("", text)
    if compact.upper().startswith("PL") and compact[2:].isdigit():
        compact = compact[2:]
    if compact.isdigit():
        if len(compact) in (9, 14) and is_valid_regon(compact):
            return Query(IdKind.REGON, normalize_regon(compact))
        if len(compact) == 10 and is_valid_nip(compact) and not compact.startswith("00"):
            return Query(IdKind.NIP, compact)
        if len(compact) <= 10:
            return Query(IdKind.KRS, normalize_krs(compact))
        raise ValueError(f"unrecognised identifier: {raw!r}")
    if len(text) < 2:
        raise ValueError("query too short")
    return Query(IdKind.NAME, text)


def search_key(name: str) -> str:
    """Accent-insensitive, case-insensitive key used for name search."""
    decomposed = unicodedata.normalize("NFKD", name.replace("ł", "l").replace("Ł", "L"))
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", stripped).strip().lower()


def like_pattern(text: str) -> str:
    """``%text%`` for SQL LIKE with the user's own wildcards escaped (default escape ``\\``)."""
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"
