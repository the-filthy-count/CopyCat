"""Scan the input folder: enqueue new/changed videos, prune deleted ones."""
from __future__ import annotations

import logging
import shutil
from pathlib import Path

from sqlmodel import select

from . import config, filmstrip
from .db import get_session
from .models import ScanRun, State, Status, Video, utcnow

logger = logging.getLogger("copycat.scanner")


def _is_video(path: Path) -> bool:
    return path.suffix.lower() in config.VIDEO_EXTENSIONS


def scan_input_folder() -> ScanRun:
    """Walk every input dir; insert new files, re-queue changed, drop missing."""
    settings = config.get_settings()
    roots = settings.input_paths
    resolved_roots = [r.resolve() for r in roots if r.exists()]

    missing = [str(r) for r in roots if not r.exists()]
    if missing:
        logger.warning("input dirs not found, skipped: %s", ", ".join(missing))

    run = ScanRun(started_at=utcnow())
    seen = 0
    discovered = 0
    removed = 0

    with get_session() as session:
        for root in roots:
            if not root.exists():
                continue
            # Skip this directory's own (per-directory) trash folder. Guard
            # against a trash path that resolves to the root itself (or an
            # ancestor) — that would make every file look like it's "inside
            # trash" and skip the entire folder. config.sanitize_trash_dirname
            # should prevent this, but never let a bad name blank a scan.
            try:
                root_resolved = root.resolve()
                trash = settings.trash_path_for(root).resolve()
                if trash == root_resolved or trash in root_resolved.parents:
                    logger.warning(
                        "trash path %s would cover input dir %s; ignoring trash "
                        "skip for this scan", trash, root_resolved,
                    )
                    trash = None
            except OSError:
                trash = None
            root_seen = 0
            walk = root.rglob("*") if settings.recursive else root.glob("*")
            for path in walk:
                if not path.is_file() or not _is_video(path):
                    continue
                if trash is not None:
                    try:
                        rp = path.resolve()
                        if rp == trash or trash in rp.parents:
                            continue
                    except OSError:
                        pass

                seen += 1
                root_seen += 1
                try:
                    stat = path.stat()
                except OSError:
                    continue
                abs_path = str(path.resolve())

                existing = session.exec(
                    select(Video).where(Video.path == abs_path)
                ).first()

                if existing is None:
                    session.add(Video(
                        path=abs_path,
                        filename=path.name,
                        size=stat.st_size,
                        mtime=stat.st_mtime,
                        status=Status.pending,
                    ))
                    discovered += 1
                elif (existing.size != stat.st_size
                      or abs(existing.mtime - stat.st_mtime) > 1e-6):
                    # File changed on disk -> reprocess.
                    existing.size = stat.st_size
                    existing.mtime = stat.st_mtime
                    existing.status = Status.pending
                    existing.sha256 = None
                    existing.phash_signature = None
                    existing.group_id = None
                    existing.error = None
                    session.add(existing)
                    discovered += 1

            logger.info("scanned %s: %s video files found", root, root_seen)

        # Prune records that should no longer appear: a file gone from disk, or
        # an active video whose folder is no longer in the input-dir list.
        # Trashed videos live under the trash folder, so only drop them if the
        # file itself is missing. Permanently-deleted rows are kept as history.
        def _under_a_root(p: Path) -> bool:
            try:
                rp = p.resolve()
            except OSError:
                return False
            return any(root == rp or root in rp.parents for root in resolved_roots)

        tracked = session.exec(
            select(Video).where(Video.state.in_([State.active, State.trashed]))
        ).all()
        for video in tracked:
            path = Path(video.path)
            gone = not path.exists()
            dropped = (video.state == State.active and not gone
                       and not _under_a_root(path))
            if not gone and not dropped:
                continue
            thumbs = filmstrip.thumb_dir_for(video.id)
            if thumbs.exists():
                shutil.rmtree(thumbs, ignore_errors=True)
            session.delete(video)
            removed += 1

        run.seen = seen
        run.discovered = discovered
        run.finished_at = utcnow()
        session.add(run)
        session.commit()
        session.refresh(run)
        if removed:
            logger.info("pruned %s videos whose files no longer exist", removed)
        return run
