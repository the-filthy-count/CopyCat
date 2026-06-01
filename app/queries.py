"""Read helpers shared between page and API routes."""
from __future__ import annotations

import math
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

from sqlmodel import Session, func, select

from . import config, hashing
from .models import ScanRun, State, Status, Video

# Donut geometry (shared with the dashboard template).
DONUT_R = 52
DONUT_CIRC = 2 * math.pi * DONUT_R


def _donut_segments(parts: List[tuple]) -> List[dict]:
    """Build SVG stroke-dash segments for a donut from (label, value, color)."""
    total = sum(v for _, v, _ in parts) or 1
    segments = []
    accum = 0.0
    for label, value, color in parts:
        if value <= 0:
            continue
        frac = value / total
        seg_len = frac * DONUT_CIRC
        segments.append({
            "label": label,
            "value": value,
            "color": color,
            "pct": round(frac * 100),
            "dash": f"{seg_len:.2f} {DONUT_CIRC - seg_len:.2f}",
            "offset": f"{-accum:.2f}",
        })
        accum += seg_len
    return segments


def dashboard_data(session: Session) -> dict:
    """Assemble every dynamic value the dashboard renders (page + live poll)."""
    counts = queue_counts(session)
    scan = latest_scan(session)
    groups = duplicate_groups(session)
    reclaimable = reclaimable_bytes(groups)
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

    return {
        "counts": counts,
        "scan": scan,
        "group_count": len(groups),
        "reclaimable": reclaimable,
        "total_size": total_size,
        "errors": errors,
        "unique": unique,
        "in_groups": in_groups,
        "donut": donut,
        "donut_total": unique + in_groups + len(errors),
        "donut_r": DONUT_R,
        "donut_circ": round(DONUT_CIRC, 2),
        "top_groups": top_groups,
        "max_group_size": max_group_size,
    }


def queue_counts(session: Session) -> Dict[str, int]:
    counts = {s.value: 0 for s in Status}
    rows = session.exec(
        select(Video.status, func.count())
        .where(Video.state == State.active)
        .group_by(Video.status)
    ).all()
    for status, n in rows:
        counts[status.value if hasattr(status, "value") else status] = n
    counts["total"] = sum(counts[s.value] for s in Status)
    return counts


def latest_scan(session: Session) -> ScanRun | None:
    return session.exec(
        select(ScanRun).order_by(ScanRun.id.desc())
    ).first()


def duplicate_groups(session: Session) -> List[List[Video]]:
    """Return active duplicate groups as lists of videos, largest savings first."""
    rows = session.exec(
        select(Video)
        .where(Video.state == State.active, Video.group_id != None)  # noqa: E711
        .order_by(Video.group_id, Video.size.desc())
    ).all()
    grouped: Dict[int, List[Video]] = defaultdict(list)
    for v in rows:
        grouped[v.group_id].append(v)
    groups = [g for g in grouped.values() if len(g) >= 2]
    # Sort groups by reclaimable space (sum of all-but-largest), descending.
    groups.sort(key=lambda g: sum(v.size for v in g[1:]), reverse=True)
    return groups


def reclaimable_bytes(groups: List[List[Video]]) -> int:
    return sum(sum(v.size for v in g[1:]) for g in groups)


def library_videos(session: Session) -> List[Video]:
    return session.exec(
        select(Video)
        .where(Video.state == State.active)
        .order_by(Video.filename)
    ).all()


def library_videos_by_similarity(
    session: Session,
) -> List[Tuple[Video, Optional[float]]]:
    """Order active videos so visually similar ones are adjacent.

    Greedy nearest-neighbor walk over the perceptual signatures: start from one
    video, then repeatedly append the closest not-yet-placed video. Each item is
    returned with its distance to the previous one (None for the first / for
    videos that have no signature, which are appended last in filename order).
    """
    videos = session.exec(
        select(Video).where(Video.state == State.active).order_by(Video.filename)
    ).all()
    method = config.get_settings().match_method

    parsed = {v.id: hashing.parse_signature(v.phash_signature) for v in videos}
    with_sig = [v for v in videos if any(parsed[v.id].values())]
    without_sig = [v for v in videos if not any(parsed[v.id].values())]

    def dist(a: Video, b: Video) -> float:
        return hashing.distance(parsed[a.id], parsed[b.id], method)

    ordered: List[Tuple[Video, Optional[float]]] = []
    remaining = list(with_sig)
    if remaining:
        current = remaining.pop(0)
        ordered.append((current, None))
        while remaining:
            nxt = min(remaining, key=lambda v: dist(current, v))
            ordered.append((nxt, dist(current, nxt)))
            remaining.remove(nxt)
            current = nxt

    ordered.extend((v, None) for v in without_sig)
    return ordered


def trashed_videos(session: Session) -> List[Video]:
    return session.exec(
        select(Video)
        .where(Video.state == State.trashed)
        .order_by(Video.processed_at.desc())
    ).all()
