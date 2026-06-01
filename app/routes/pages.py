"""HTML page routes."""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from .. import config, queries
from ..db import get_session
from ..models import State, Status, Video
from ..templating import templates
from sqlmodel import select

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    with get_session() as session:
        counts = queries.queue_counts(session)
        scan = queries.latest_scan(session)
        groups = queries.duplicate_groups(session)
        reclaimable = queries.reclaimable_bytes(groups)
        errors = session.exec(
            select(Video).where(Video.status == Status.error, Video.state == State.active)
        ).all()
    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "counts": counts,
            "scan": scan,
            "group_count": len(groups),
            "reclaimable": reclaimable,
            "errors": errors,
            "settings": config.get_settings(),
            "active": "dashboard",
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
