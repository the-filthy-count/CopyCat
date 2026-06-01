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
    """Walk INPUT_DIR; insert new files, re-queue changed ones, drop missing ones."""
    settings = config.get_settings()
    root = settings.input_path
    trash = settings.trash_path.resolve()

    run = ScanRun(started_at=utcnow())
    seen = 0
    discovered = 0
    removed = 0

    with get_session() as session:
        if root.exists():
            for path in root.rglob("*"):
                if not path.is_file() or not _is_video(path):
                    continue
                # Skip anything inside the trash folder.
                try:
                    if trash in path.resolve().parents or path.resolve() == trash:
                        continue
                except OSError:
                    pass

                seen += 1
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

        # Prune records whose files have disappeared from disk. Active and
        # trashed videos point at real files; if those are gone (deleted/moved
        # outside the app, or trash emptied externally), forget them and clean
        # up their thumbnails. Permanently-deleted rows are left as history.
        tracked = session.exec(
            select(Video).where(Video.state.in_([State.active, State.trashed]))
        ).all()
        for video in tracked:
            if Path(video.path).exists():
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
