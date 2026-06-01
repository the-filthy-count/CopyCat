"""File lifecycle operations: trash, permanent delete, restore, empty trash."""
from __future__ import annotations

import logging
import shutil
from pathlib import Path

from sqlmodel import select

from . import cache, config, filmstrip
from .db import get_session
from .models import State, Video, utcnow

logger = logging.getLogger("copycat.files")


def _matching_input(path: Path) -> Path | None:
    """Return the configured input dir that contains ``path`` (if any)."""
    try:
        rp = path.resolve()
    except OSError:
        return None
    for root in config.get_settings().input_paths:
        try:
            rr = root.resolve()
        except OSError:
            continue
        if rr == rp or rr in rp.parents:
            return rr
    return None


def _avoid_collision(dest: Path, tag: str = "") -> Path:
    if not dest.exists():
        return dest
    stem, suffix = dest.stem, dest.suffix
    i = 1
    while True:
        candidate = dest.with_name(f"{stem}__{tag}{i}{suffix}")
        if not candidate.exists():
            return candidate
        i += 1


def _trash_target(src: Path) -> Path:
    """Compute a collision-safe destination in the source dir's own trash.

    Trash is per-directory: a file is moved into ``<its input dir>/<trash name>``
    preserving its path relative to that input dir. Falls back to the primary
    input dir's trash if the file isn't under any configured directory.
    """
    settings = config.get_settings()
    root = _matching_input(src)
    if root is not None:
        rel = src.resolve().relative_to(root)
        trash_root = settings.trash_path_for(root)
    else:
        rel = Path(src.name)
        trash_root = settings.trash_path_for(settings.input_path)
    dest = trash_root / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    return _avoid_collision(dest)


def trash_video(video_id: int) -> bool:
    with get_session() as session:
        video = session.get(Video, video_id)
        if video is None or video.state != State.active:
            return False
        src = Path(video.path)
        video.original_path = str(src.resolve())  # remember for accurate restore
        if src.exists():
            dest = _trash_target(src)
            shutil.move(str(src), str(dest))
            video.path = str(dest.resolve())
        video.state = State.trashed
        video.group_id = None
        video.processed_at = utcnow()
        session.add(video)
        session.commit()
        logger.info("trashed video %s", video_id)
        cache.bump()
        return True


def restore_video(video_id: int) -> bool:
    """Move a trashed file back to its original location."""
    with get_session() as session:
        video = session.get(Video, video_id)
        if video is None or video.state != State.trashed:
            return False
        current = Path(video.path)
        # Prefer the exact original path; fall back to the first input dir.
        if video.original_path:
            dest = Path(video.original_path)
        else:
            dest = config.get_settings().input_path / current.name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest = _avoid_collision(dest, tag="restored")
        if current.exists():
            shutil.move(str(current), str(dest))
        video.path = str(dest.resolve())
        video.original_path = None
        video.state = State.active
        video.processed_at = utcnow()
        session.add(video)
        session.commit()
        logger.info("restored video %s", video_id)
        cache.bump()
        return True


def delete_video_permanent(video_id: int) -> bool:
    """Permanently remove the file from disk and its thumbnails."""
    with get_session() as session:
        video = session.get(Video, video_id)
        if video is None or video.state == State.deleted:
            return False
        src = Path(video.path)
        if src.exists():
            try:
                src.unlink()
            except OSError:
                logger.exception("failed to delete %s", src)
                return False
        # Remove generated thumbnails too.
        thumbs = filmstrip.thumb_dir_for(video_id)
        if thumbs.exists():
            shutil.rmtree(thumbs, ignore_errors=True)
        video.state = State.deleted
        video.group_id = None
        video.thumb_count = 0
        video.processed_at = utcnow()
        session.add(video)
        session.commit()
        logger.info("permanently deleted video %s", video_id)
        cache.bump()
        return True


def delete_video(video_id: int) -> bool:
    """Delete per the configured mode (trash by default)."""
    if config.get_settings().delete_mode == "permanent":
        return delete_video_permanent(video_id)
    return trash_video(video_id)


def empty_trash() -> int:
    """Permanently remove all trashed files. Returns count removed."""
    settings = config.get_settings()
    count = 0
    with get_session() as session:
        trashed = session.exec(
            select(Video).where(Video.state == State.trashed)
        ).all()
        for video in trashed:
            src = Path(video.path)
            if src.exists():
                try:
                    src.unlink()
                except OSError:
                    logger.exception("failed to remove %s", src)
            thumbs = filmstrip.thumb_dir_for(video.id)
            if thumbs.exists():
                shutil.rmtree(thumbs, ignore_errors=True)
            video.state = State.deleted
            video.thumb_count = 0
            session.add(video)
            count += 1
        session.commit()
    # Best-effort cleanup of every per-directory trash tree.
    for trash_root in settings.trash_paths:
        if trash_root.exists():
            shutil.rmtree(trash_root, ignore_errors=True)
    logger.info("emptied trash: %s files", count)
    cache.bump()
    return count
