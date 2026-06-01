"""Background worker: drains the processing queue and triggers grouping.

A single daemon thread owns all ffmpeg/hashing work so the web request
handlers stay responsive. The thread:

  1. Performs a folder scan when one is requested.
  2. Processes pending videos one at a time (probe -> hash -> filmstrip -> sig).
  3. Re-runs grouping once the queue drains after processing.
"""
from __future__ import annotations

import logging
import threading
from pathlib import Path

from sqlmodel import select

from . import config, filmstrip, grouping, hashing
from .db import get_session
from .models import Status, Video, utcnow
from .probe import probe
from .scanner import scan_input_folder

logger = logging.getLogger("copycat.worker")

_wake = threading.Event()
_scan_requested = threading.Event()
_thread: threading.Thread | None = None


def request_scan() -> None:
    """Ask the worker to scan the input folder, then wake it."""
    _scan_requested.set()
    _wake.set()


def request_regroup() -> None:
    """Force a regrouping pass on the next loop iteration."""
    _regroup_pending.set()
    _wake.set()


def request_recompute() -> None:
    """Recompute every video's multi-signal fingerprint from its thumbnails."""
    _recompute_pending.set()
    _wake.set()


_regroup_pending = threading.Event()
_recompute_pending = threading.Event()


def _recompute_signatures() -> None:
    """Rebuild perceptual signatures from on-disk thumbnails (no ffmpeg).

    Used to backfill legacy single-hash signatures and to apply a changed
    frame-hash set to already-processed videos cheaply.
    """
    with get_session() as session:
        rows = session.exec(
            select(Video).where(Video.status == Status.done)
        ).all()
        targets = [(v.id, v.thumb_count) for v in rows]

    updated = 0
    for video_id, _ in targets:
        thumb_dir = filmstrip.thumb_dir_for(video_id)
        if not thumb_dir.exists():
            continue
        frames = sorted(thumb_dir.glob("frame_*.jpg"))
        if not frames:
            continue
        try:
            signature = hashing.build_signature(frames)
        except Exception:
            logger.exception("recompute failed for video %s", video_id)
            continue
        with get_session() as session:
            video = session.get(Video, video_id)
            if video is not None:
                video.phash_signature = signature
                video.thumb_count = len(frames)
                session.add(video)
                session.commit()
        updated += 1
    logger.info("recomputed signatures for %s videos", updated)


def _has_legacy_signatures() -> bool:
    with get_session() as session:
        rows = session.exec(
            select(Video).where(Video.status == Status.done)
        ).all()
        return any(hashing.is_legacy_signature(v.phash_signature) for v in rows)


def _next_pending_id() -> int | None:
    with get_session() as session:
        row = session.exec(
            select(Video).where(Video.status == Status.pending).order_by(Video.id)
        ).first()
        return row.id if row else None


def _process_one(video_id: int) -> None:
    settings = config.get_settings()
    with get_session() as session:
        video = session.get(Video, video_id)
        if video is None or video.status != Status.pending:
            return
        video.status = Status.processing
        session.add(video)
        session.commit()
        path = Path(video.path)

    try:
        if not path.exists():
            raise FileNotFoundError(f"file no longer on disk: {path}")

        meta = probe(path)
        sha = hashing.sha256_file(path)
        frames = filmstrip.extract_filmstrip(
            video_id, path, meta.duration,
            settings.frames_per_strip, settings.thumb_width,
        )
        signature = hashing.build_signature(frames) if frames else None

        with get_session() as session:
            video = session.get(Video, video_id)
            video.duration = meta.duration
            video.width = meta.width
            video.height = meta.height
            video.codec = meta.codec
            video.fps = meta.fps
            video.bitrate = meta.bitrate
            video.sha256 = sha
            video.phash_signature = signature
            video.thumb_count = len(frames)
            video.status = Status.done
            video.error = None
            video.processed_at = utcnow()
            session.add(video)
            session.commit()
        logger.info("processed video %s (%s frames)", video_id, len(frames))
    except Exception as exc:  # noqa: BLE001 - record any failure on the row
        logger.exception("failed to process video %s", video_id)
        with get_session() as session:
            video = session.get(Video, video_id)
            if video is not None:
                video.status = Status.error
                video.error = str(exc)[:1000]
                video.processed_at = utcnow()
                session.add(video)
                session.commit()


def _loop() -> None:
    logger.info("worker thread started")
    dirty = False  # processed something since the last grouping pass
    # Backfill legacy single-hash signatures left by older versions.
    if _has_legacy_signatures():
        logger.info("legacy signatures detected; scheduling recompute")
        _recompute_pending.set()
    while True:
        if _scan_requested.is_set():
            _scan_requested.clear()
            try:
                run = scan_input_folder()
                logger.info("scan complete: %s seen, %s queued", run.seen, run.discovered)
            except Exception:
                logger.exception("scan failed")

        pending_id = _next_pending_id()
        if pending_id is not None:
            _process_one(pending_id)
            dirty = True
            continue  # keep draining the queue before grouping

        if _recompute_pending.is_set():
            _recompute_pending.clear()
            try:
                _recompute_signatures()
            except Exception:
                logger.exception("recompute failed")
            dirty = True
            continue

        # Queue is empty: run grouping if processing happened or one was requested.
        if dirty or _regroup_pending.is_set():
            dirty = False
            _regroup_pending.clear()
            try:
                grouping.regroup()
            except Exception:
                logger.exception("regroup failed")
            continue

        # Nothing to do: sleep until woken or a periodic re-check.
        _wake.wait(timeout=5.0)
        _wake.clear()


def start_worker() -> None:
    global _thread
    if _thread is not None and _thread.is_alive():
        return
    _thread = threading.Thread(target=_loop, name="copycat-worker", daemon=True)
    _thread.start()
