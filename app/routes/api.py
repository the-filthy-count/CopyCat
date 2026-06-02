"""HTMX/action endpoints. Mutating routes re-render the affected list partial."""
from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from .. import cache, config, files, queries
from ..db import get_session, set_settings
from ..models import State, Video
from ..templating import templates
from ..worker import request_recompute, request_regroup, request_scan
from sqlmodel import select

router = APIRouter(prefix="/api")


# --- Scan / status (dashboard) ---------------------------------------------

@router.post("/scan", response_class=HTMLResponse)
def scan(request: Request):
    request_scan()
    return _status_partial(request)


@router.get("/status", response_class=HTMLResponse)
def status(request: Request):
    return _status_partial(request)


def _status_partial(request: Request) -> HTMLResponse:
    """Live dashboard fragment: queue stats + out-of-band donut & gauge."""
    data = cache.get_dashboard_data()
    return templates.TemplateResponse(
        "partials/dashboard_live.html",
        {"request": request, **data},
    )


# --- Group actions ----------------------------------------------------------

def _groups_partial(request: Request) -> HTMLResponse:
    with get_session() as session:
        groups = queries.duplicate_groups(session)
        reclaimable = queries.reclaimable_bytes(groups)
    return templates.TemplateResponse(
        "partials/groups_list.html",
        {"request": request, "groups": groups, "reclaimable": reclaimable},
    )


@router.post("/videos/{video_id}/delete", response_class=HTMLResponse)
def delete_from_group(video_id: int, request: Request):
    files.delete_video(video_id)
    request_regroup()
    return _groups_partial(request)


@router.post("/groups/{group_id}/keep/{keep_id}", response_class=HTMLResponse)
def keep_one(group_id: int, keep_id: int, request: Request):
    """Delete every member of the group except the chosen one."""
    with get_session() as session:
        members = session.exec(
            select(Video).where(
                Video.group_id == group_id, Video.state == State.active
            )
        ).all()
        victim_ids = [v.id for v in members if v.id != keep_id]
    for vid in victim_ids:
        files.delete_video(vid)
    request_regroup()
    return _groups_partial(request)


@router.post("/videos/{video_id}/not-duplicate", response_class=HTMLResponse)
def not_duplicate(video_id: int, request: Request):
    with get_session() as session:
        video = session.get(Video, video_id)
        if video is not None:
            video.pinned_out = True
            video.group_id = None
            session.add(video)
            session.commit()
    request_regroup()
    return _groups_partial(request)


# --- Library actions --------------------------------------------------------

def _library_partial(request: Request) -> HTMLResponse:
    with get_session() as session:
        items = queries.library_videos_by_similarity(session)
    return templates.TemplateResponse(
        "partials/library_list.html",
        {"request": request, "items": items},
    )


@router.post("/videos/{video_id}/delete-library", response_class=HTMLResponse)
def delete_from_library(video_id: int, request: Request):
    files.delete_video(video_id)
    request_regroup()
    return _library_partial(request)


# --- Trash actions ----------------------------------------------------------

def _trash_partial(request: Request) -> HTMLResponse:
    with get_session() as session:
        videos = queries.trashed_videos(session)
    return templates.TemplateResponse(
        "partials/trash_list.html",
        {"request": request, "videos": videos},
    )


@router.post("/videos/{video_id}/restore", response_class=HTMLResponse)
def restore(video_id: int, request: Request):
    files.restore_video(video_id)
    request_regroup()
    return _trash_partial(request)


@router.post("/videos/{video_id}/delete-permanent", response_class=HTMLResponse)
def delete_permanent(video_id: int, request: Request):
    files.delete_video_permanent(video_id)
    return _trash_partial(request)


@router.post("/trash/empty", response_class=HTMLResponse)
def empty_trash(request: Request):
    files.empty_trash()
    return _trash_partial(request)


# --- Settings ---------------------------------------------------------------

@router.post("/settings")
def save_settings(
    input_dirs: str = Form(...),
    trash_dirname: str = Form(".copycat-trash"),
    delete_mode: str = Form("trash"),
    thumb_width: int = Form(240),
    similarity_threshold: float = Form(0.15),
    duration_tolerance: float = Form(2.0),
    match_method: str = Form("combined"),
    match_ignore_duration: bool = Form(False),
    recursive: bool = Form(False),
):
    set_settings({
        "input_dirs": input_dirs,
        "trash_dirname": config.sanitize_trash_dirname(trash_dirname),
        "delete_mode": delete_mode,
        "thumb_width": str(thumb_width),
        "similarity_threshold": str(similarity_threshold),
        "duration_tolerance": str(duration_tolerance),
        "match_method": match_method,
        "match_ignore_duration": "1" if match_ignore_duration else "0",
        "recursive": "1" if recursive else "0",
    })
    request_regroup()
    return RedirectResponse(url="/settings?saved=true", status_code=303)


@router.post("/regroup")
def regroup_now():
    request_regroup()
    return RedirectResponse(url="/groups", status_code=303)


@router.post("/recompute")
def recompute_now():
    """Rebuild perceptual fingerprints from existing thumbnails, then regroup."""
    request_recompute()
    return RedirectResponse(url="/settings?recomputing=true", status_code=303)
