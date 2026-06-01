"""HTML page routes."""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from .. import config, queries
from ..db import get_session
from ..templating import templates

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    with get_session() as session:
        data = queries.dashboard_data(session)
    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "settings": config.get_settings(),
            "active": "dashboard",
            **data,
        },
    )


@router.get("/groups", response_class=HTMLResponse)
def groups_page(request: Request):
    with get_session() as session:
        groups = queries.duplicate_groups(session)
        reclaimable = queries.reclaimable_bytes(groups)
    return templates.TemplateResponse(
        "groups.html",
        {
            "request": request,
            "groups": groups,
            "reclaimable": reclaimable,
            "active": "groups",
        },
    )


@router.get("/library", response_class=HTMLResponse)
def library_page(request: Request):
    with get_session() as session:
        items = queries.library_videos_by_similarity(session)
    return templates.TemplateResponse(
        "library.html",
        {"request": request, "items": items, "active": "library"},
    )


@router.get("/trash", response_class=HTMLResponse)
def trash_page(request: Request):
    with get_session() as session:
        videos = queries.trashed_videos(session)
    return templates.TemplateResponse(
        "trash.html",
        {"request": request, "videos": videos, "active": "trash"},
    )


@router.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request, saved: bool = False, recomputing: bool = False):
    return templates.TemplateResponse(
        "settings.html",
        {
            "request": request,
            "settings": config.get_settings(),
            "saved": saved,
            "recomputing": recomputing,
            "active": "settings",
        },
    )
