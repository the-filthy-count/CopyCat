"""Read helpers shared between page and API routes."""
from __future__ import annotations

from collections import defaultdict
from typing import Dict, List, Optional, Tuple

from sqlmodel import Session, func, select

from . import config, hashing
from .models import ScanRun, State, Status, Video


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
