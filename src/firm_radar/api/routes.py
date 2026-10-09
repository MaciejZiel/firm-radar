"""JSON API, mounted under ``/api/v1``."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, status

from firm_radar.api.models import (
    ChangeOut,
    CompanySummary,
    DiffOut,
    ErrorOut,
    HistoryOut,
    ProfileOut,
    RefreshOut,
    SearchOut,
    TimelineEntry,
)
from firm_radar.identifiers import IdKind, detect
from firm_radar.schemas import CompanyData
from firm_radar.services.diff import diff
from firm_radar.services.profiles import (
    AllSourcesFailed,
    CompanyNotFound,
    InvalidQuery,
    ProfileService,
)

router = APIRouter(prefix="/api/v1")

CompanyId = Annotated[int, Path(ge=1, description="Internal company id", examples=[1])]
ERRORS: dict[int | str, dict[str, Any]] = {
    404: {"model": ErrorOut, "description": "Unknown company"},
    503: {"model": ErrorOut, "description": "Upstream registry unavailable"},
}


def get_profiles(request: Request) -> ProfileService:
    service: ProfileService = request.app.state.profiles
    return service


Profiles = Annotated[ProfileService, Depends(get_profiles)]


@router.get(
    "/search",
    response_model=SearchOut,
    tags=["companies"],
    summary="Find a company by KRS, NIP, REGON or name",
    responses={400: {"model": ErrorOut, "description": "Malformed identifier"}, **ERRORS},
)
async def search(
    profiles: Profiles,
    q: Annotated[
        str,
        Query(
            min_length=2,
            max_length=200,
            description=(
                "KRS (up to 10 digits), NIP (10 digits, checksum validated), REGON (9 or 14 "
                "digits) or part of a name. Prefix with `krs:`, `nip:` or `regon:` to force "
                "the type. Identifiers are looked up in the registries; names only match "
                "companies already known to this instance."
            ),
            examples=["1234563218", "krs:999901", "przykładowa"],
        ),
    ],
) -> SearchOut:
    try:
        query = detect(q)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    if query.kind is IdKind.NAME:
        companies = await profiles.search_local(query.value)
        return SearchOut(
            query=q,
            kind="name",
            value=query.value,
            results=[CompanySummary.of(c) for c in companies],
            note=None
            if companies
            else "Registries offer no name search; look the company up by KRS or NIP first.",
        )
    try:
        result = await profiles.resolve(query)
    except CompanyNotFound:
        return SearchOut(query=q, kind=query.kind.value, value=query.value, results=[])
    except InvalidQuery as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    except AllSourcesFailed as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, f"registries unavailable: {exc}"
        ) from exc
    return SearchOut(
        query=q,
        kind=query.kind.value,
        value=query.value,
        results=[CompanySummary.of(result.company)],
    )


@router.get(
    "/companies/{company_id}",
    response_model=ProfileOut,
    tags=["companies"],
    summary="Company profile from the latest snapshot, with source references",
    responses=ERRORS,
)
async def profile(company_id: CompanyId, profiles: Profiles) -> ProfileOut:
    found = await profiles.get(company_id)
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "company not found")
    return ProfileOut.of(*found)


@router.post(
    "/companies/{company_id}/refresh",
    response_model=RefreshOut,
    tags=["companies"],
    summary="Re-read the registries now (subject to the response cache TTL)",
    responses=ERRORS,
)
async def refresh(company_id: CompanyId, profiles: Profiles) -> RefreshOut:
    try:
        result = await profiles.refresh(company_id)
    except CompanyNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "company not found") from exc
    except AllSourcesFailed as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, f"registries unavailable: {exc}"
        ) from exc
    return RefreshOut(
        company_id=result.company.id,
        snapshot_id=result.snapshot.id,
        new_snapshot=result.created,
        changes=[ChangeOut.of(c) for c in result.changes],
    )


@router.get(
    "/companies/{company_id}/history",
    response_model=HistoryOut,
    tags=["history"],
    summary="Timeline of detected changes, newest first",
    responses={404: ERRORS[404]},
)
async def history(company_id: CompanyId, profiles: Profiles) -> HistoryOut:
    entries = await profiles.history(company_id)
    if not entries:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "company not found")
    return HistoryOut(
        company_id=company_id,
        snapshots=len(entries),
        timeline=[
            TimelineEntry(
                snapshot_id=s.id, taken_at=s.taken_at, changes=[ChangeOut.of(c) for c in changes]
            )
            for s, changes in entries
        ],
    )


@router.get(
    "/companies/{company_id}/diff",
    response_model=DiffOut,
    tags=["history"],
    summary="Compare two snapshots (defaults: the latest one against its predecessor)",
    responses={404: ERRORS[404]},
)
async def snapshot_diff(
    company_id: CompanyId,
    profiles: Profiles,
    from_snapshot: Annotated[int | None, Query(alias="from", ge=1)] = None,
    to_snapshot: Annotated[int | None, Query(alias="to", ge=1)] = None,
) -> DiffOut:
    pair = await profiles.snapshot_pair(company_id, from_snapshot, to_snapshot)
    if pair is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "snapshot not found")
    older, newer = pair
    changes = diff(CompanyData.model_validate(older.data), CompanyData.model_validate(newer.data))
    return DiffOut(
        company_id=company_id,
        from_snapshot=older.id,
        to_snapshot=newer.id,
        from_taken_at=older.taken_at,
        to_taken_at=newer.taken_at,
        changes=[ChangeOut.of(c) for c in changes],
    )
