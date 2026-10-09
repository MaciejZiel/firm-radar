"""Recorded upstream responses replayed with aioresponses.

Every fixture mirrors the *structure* of a real response from the official API, but all
values (names, numbers, addresses) are fictional. Tests never reach the network: any request
without a registered response fails.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from aioresponses import aioresponses

FIXTURES = Path(__file__).parent / "fixtures"

KRS = "https://api-krs.ms.gov.pl/api/krs"
WL = "https://wl-api.mf.gov.pl/api"
BZP = "https://ezamowienia.gov.pl/mo-board/api/v1"


def load(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def krs_extract(
    mock: aioresponses, krs: str, fixture: str | None, *, register: str = "P", repeat: bool = False
) -> None:
    url = re.compile(rf"^{re.escape(KRS)}/OdpisAktualny/{krs}\?.*rejestr={register}.*$")
    if fixture is None:
        mock.get(url, status=404, payload={"status": 404, "title": "Not Found"}, repeat=repeat)
    else:
        mock.get(url, payload=load(fixture), repeat=repeat)


def whitelist(
    mock: aioresponses, kind: str, value: str, fixture: str, *, status: int = 200
) -> None:
    url = re.compile(rf"^{re.escape(WL)}/search/{kind}/{value}\?date=\d{{4}}-\d{{2}}-\d{{2}}$")
    mock.get(url, status=status, payload=load(fixture))


def bzp_notices(mock: aioresponses, fixture: str) -> None:
    mock.get(re.compile(rf"^{re.escape(BZP)}/notice\?.*$"), payload=load(fixture))
