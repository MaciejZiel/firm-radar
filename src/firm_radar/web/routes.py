"""Server-rendered UI (Jinja2 + htmx), Polish by default with an English toggle."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from functools import partial
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy import select

from firm_radar.api.health import build_health
from firm_radar.api.models import ChangeOut, ProcurementOut, SearchOut
from firm_radar.api.routes import search_companies
from firm_radar.models import Company
from firm_radar.schemas import CompanyData, SourceRef
from firm_radar.services.diff import VAT_NOT_REGISTERED, diff
from firm_radar.services.procurement import ProcurementService
from firm_radar.services.profiles import (
    AllSourcesFailed,
    CompanyNotFound,
    InvalidQuery,
    ProfileService,
)
from firm_radar.sources.base import WARSAW
from firm_radar.sources.catalog import CATALOG
from firm_radar.web.i18n import LANGS, Lang, translate

TEMPLATES = Jinja2Templates(directory=Path(__file__).parent / "templates")
LANG_COOKIE = "lang"

# Real, large public companies used as clickable examples on the search page.
EXAMPLES = [
    ("0000019193", "PKP S.A."),
    ("5260250995", "Orange Polska S.A."),
]

router = APIRouter(include_in_schema=False)


def _lang(request: Request) -> Lang:
    wanted = request.query_params.get("lang") or request.cookies.get(LANG_COOKIE) or "pl"
    return wanted if wanted in LANGS else "pl"  # type: ignore[return-value]


def _money(amount: str | None, currency: str = "PLN", lang: Lang = "pl") -> str:
    if not amount:
        return ""
    try:
        value = Decimal(amount)
    except InvalidOperation:
        return f"{amount} {currency}"
    text = f"{value:,.2f}"
    if lang == "pl":
        text = text.replace(",", " ").replace(".", ",")
    return f"{text} {'zł' if currency == 'PLN' and lang == 'pl' else currency}"


def _date(value: Any, with_time: bool = False, lang: Lang = "pl") -> str:
    if value is None or value == "":
        return "–"
    if isinstance(value, str):
        text = value
        try:
            value = datetime.fromisoformat(text) if "T" in text else date.fromisoformat(text)
        except ValueError:
            return text
    if isinstance(value, datetime):
        local = value.astimezone(WARSAW)
        fmt = "%d.%m.%Y %H:%M" if lang == "pl" else "%Y-%m-%d %H:%M"
        return local.strftime(fmt if with_time else fmt.split(" ")[0])
    if isinstance(value, date):
        return value.strftime("%d.%m.%Y" if lang == "pl" else "%Y-%m-%d")
    return str(value)


def _translate(key: str, lang: Lang) -> str:
    return translate(key, lang)


def _vat_label(status: str | None, lang: Lang) -> str:
    mapping = {
        "Czynny": "company.vat.active",
        "Zwolniony": "company.vat.exempt",
        "REMOVED": "company.vat.removed",
        VAT_NOT_REGISTERED: "company.vat.none",
        None: "company.vat.unknown",
    }
    key = mapping.get(status)
    return translate(key, lang) if key else str(status)


def _vat_state(data: CompanyData) -> str | None:
    if data.vat is not None:
        return data.vat.status or "REMOVED"
    if data.vat_registered is False:
        return VAT_NOT_REGISTERED
    return None


def _render(
    request: Request, template: str, context: dict[str, Any], status_code: int = 200
) -> HTMLResponse:
    lang = _lang(request)
    query_lang = request.query_params.get("lang")
    base = {
        "request": request,
        "lang": lang,
        "other_lang": "en" if lang == "pl" else "pl",
        "t": partial(_translate, lang=lang),
        "money": partial(_money, lang=lang),
        "fdate": partial(_date, lang=lang),
        "vat_label": partial(_vat_label, lang=lang),
    }
    response = TEMPLATES.TemplateResponse(
        request, template, {**base, **context}, status_code=status_code
    )
    if query_lang in LANGS:
        response.set_cookie(LANG_COOKIE, query_lang, max_age=365 * 24 * 3600, samesite="lax")
    return response


def _profiles(request: Request) -> ProfileService:
    service: ProfileService = request.app.state.profiles
    return service


def _procurement(request: Request) -> ProcurementService:
    service: ProcurementService = request.app.state.procurement
    return service


@router.get("/", response_class=HTMLResponse)
async def index(request: Request) -> Response:
    async with request.app.state.db.sessionmaker() as session:
        recent = list(
            await session.scalars(
                select(Company).order_by(Company.last_checked_at.desc().nulls_last()).limit(8)
            )
        )
    return _render(request, "index.html", {"recent": recent, "examples": EXAMPLES, "q": ""})


@router.get("/szukaj", response_class=HTMLResponse)
async def search(request: Request, q: str = "") -> Response:
    q = q.strip()
    partial = (
        request.headers.get("hx-request") == "true"
        and request.headers.get("hx-history-restore-request") != "true"
    )
    result: SearchOut | None = None
    error: str | None = None
    if len(q) >= 2:
        try:
            result = await search_companies(q, _profiles(request), _procurement(request))
        except (ValueError, InvalidQuery) as exc:
            error = str(exc)
        except AllSourcesFailed:
            error = translate("error.unavailable", _lang(request))
    if result is not None and result.kind != "name" and len(result.results) == 1:
        target = f"/firma/{result.results[0].id}"
        if partial:
            return Response(status_code=200, headers={"HX-Redirect": target})
        return RedirectResponse(target, status_code=303)
    context = {"q": q, "result": result, "error": error}
    if partial:
        return _render(request, "_results.html", context)
    return _render(request, "index.html", {**context, "recent": [], "examples": EXAMPLES})


@router.get("/firma/{company_id}", response_class=HTMLResponse)
async def company(request: Request, company_id: int) -> Response:
    profiles = _profiles(request)
    found = await profiles.get(company_id)
    if found is None:
        return _render(
            request,
            "error.html",
            {"message": translate("error.not_found", _lang(request))},
            status_code=404,
        )
    company_row, snapshot = found
    data = CompanyData.model_validate(snapshot.data)
    awards = (
        ProcurementOut.of(await _procurement(request).summary(company_row.nip))
        if company_row.nip
        else None
    )
    timeline = [
        (s, [ChangeOut.of(c) for c in changes]) for s, changes in await profiles.history(company_id)
    ]
    return _render(
        request,
        "company.html",
        {
            "company": company_row,
            "snapshot": snapshot,
            "data": data,
            "vat_state": _vat_state(data),
            "awards": awards,
            "timeline": timeline,
            "sources": [SourceRef.model_validate(r) for r in company_row.source_refs or []],
        },
    )


@router.post("/firma/{company_id}/odswiez")
async def refresh(request: Request, company_id: int) -> Response:
    try:
        await _profiles(request).refresh(company_id)
    except CompanyNotFound:
        pass
    except AllSourcesFailed:
        return _render(
            request,
            "error.html",
            {"message": translate("error.unavailable", _lang(request))},
            status_code=503,
        )
    return RedirectResponse(f"/firma/{company_id}", status_code=303)


@router.get("/firma/{company_id}/porownaj", response_class=HTMLResponse)
async def compare(
    request: Request, company_id: int, od: int | None = None, do: int | None = None
) -> Response:
    pair = await _profiles(request).snapshot_pair(company_id, od, do)
    if pair is None:
        return _render(
            request,
            "error.html",
            {"message": translate("error.not_found", _lang(request))},
            status_code=404,
        )
    older, newer = pair
    changes = [
        ChangeOut.of(c)
        for c in diff(
            CompanyData.model_validate(older.data), CompanyData.model_validate(newer.data)
        )
    ]
    return _render(
        request,
        "_diff.html",
        {"older": older, "newer": newer, "changes": changes, "company_id": company_id},
    )


@router.get("/zrodla", response_class=HTMLResponse)
async def sources(request: Request) -> Response:
    state = request.app.state
    health = await build_health(state.settings, state.sources.store, state.db.sessionmaker)
    catalog = {name.value: info for name, info in CATALOG.items()}
    return _render(request, "sources.html", {"health": health, "catalog": catalog})
