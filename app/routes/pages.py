"""HTML page routes."""
from __future__ import annotations

import math

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from .. import config, queries
from ..db import get_session
from ..models import State, Status, Video
from ..templating import templates
from sqlmodel import select

router = APIRouter()

# Donut geometry (shared with the template).
_DONUT_R = 52
_DONUT_CIRC = 2 * math.pi * _DONUT_R


def _donut_segments(parts: list[tuple[str, int, str]]) -> list[dict]:
    """Build SVG stroke-dash segments for a donut from (label, value, color)."""
    total = sum(v for _, v, _ in parts) or 1
    segments = []
    accum = 0.0
    for label, value, color in parts:
        if value <= 0:
            continue
        frac = value / total
        seg_len = frac * _DONUT_CIRC
        segments.append({
            "label": label,
            "value": value,
            "color": color,
            "pct": round(frac * 100),
            "dash": f"{seg_len:.2f} {_DONUT_CIRC - seg_len:.2f}",
            "offset": f"{-accum:.2f}",
        })
        accum += seg_len
    return segments


@router.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    with get_session() as session:
        counts = queries.queue_counts(session)
        scan = queries.latest_scan(session)
        groups = queries.duplicate_groups(session)
        reclaimable = queries.reclaimable_bytes(groups)
        active = session.exec(select(Video).where(Video.state == State.active)).all()
        errors = [v for v in active if v.status == Status.error]

    total_size = sum(v.size or 0 for v in active)
    done_active = [v for v in active if v.status == Status.done]
    in_groups = sum(len(g) for g in groups)
    unique = max(len(done_active) - in_groups, 0)

    donut = _donut_segments([
        ("Unique", unique, "#36e07a"),
        ("In duplicate groups", in_groups, "#ffc14d"),
        ("Errors", len(errors), "#ff5f72"),
    ])
    donut_total = unique + in_groups + len(errors)

    # Top duplicate groups by reclaimable size for the bar chart.
    top_groups = []
    for g in groups[:6]:
        group_size = sum(v.size or 0 for v in g)
        top_groups.append({
            "name": g[0].filename,
            "members": len(g),
            "size": group_size,
            "reclaim": sum(v.size or 0 for v in g[1:]),
        })
    max_group_size = max((tg["size"] for tg in top_groups), default=1) or 1

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "counts": counts,
            "scan": scan,
            "group_count": len(groups),
            "reclaimable": reclaimable,
            "total_size": total_size,
            "errors": errors,
            "unique": unique,
            "in_groups": in_groups,
            "donut": donut,
            "donut_total": donut_total,
            "donut_r": _DONUT_R,
            "donut_circ": round(_DONUT_CIRC, 2),
            "top_groups": top_groups,
            "max_group_size": max_group_size,
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
