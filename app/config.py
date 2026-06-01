"""Configuration: environment defaults overlaid by DB-backed settings.

Environment variables seed the initial values on first run. After that the
Setting table is the source of truth and is editable from the Settings page.
Call ``get_settings()`` to read the current effective config.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# --- Static, process-level paths (not user-editable at runtime) -------------

DATA_DIR = Path(os.environ.get("DATA_DIR", "./data")).resolve()
DB_PATH = DATA_DIR / "copycat.db"
THUMBS_DIR = DATA_DIR / "thumbs"

VIDEO_EXTENSIONS = {
    ".mp4", ".mkv", ".avi", ".mov", ".webm", ".m4v",
    ".wmv", ".flv", ".mpg", ".mpeg", ".ts", ".m2ts",
}

# Setting keys persisted in the DB, with their env-seeded defaults.
DEFAULTS: dict[str, str] = {
    "input_dir": os.environ.get("INPUT_DIR", "/media"),
    "trash_dir": os.environ.get("TRASH_DIR", ""),  # empty -> derived from input_dir
    "delete_mode": os.environ.get("DELETE_MODE", "trash"),  # trash | permanent
    "frames_per_strip": os.environ.get("FRAMES_PER_STRIP", "10"),
    "thumb_width": os.environ.get("THUMB_WIDTH", "240"),
    "similarity_threshold": os.environ.get("SIMILARITY_THRESHOLD", "0.15"),
    "duration_tolerance": os.environ.get("DURATION_TOLERANCE", "2"),
    # combined | phash | dhash | ahash | whash
    "match_method": os.environ.get("MATCH_METHOD", "combined"),
    # "1" -> match on visuals regardless of runtime (catches trimmed copies)
    "match_ignore_duration": os.environ.get("MATCH_IGNORE_DURATION", "1"),
}


@dataclass
class Settings:
    input_dir: str
    trash_dir: str
    delete_mode: str
    frames_per_strip: int
    thumb_width: int
    similarity_threshold: float
    duration_tolerance: float
    match_method: str
    match_ignore_duration: bool

    @property
    def input_path(self) -> Path:
        return Path(self.input_dir)

    @property
    def trash_path(self) -> Path:
        if self.trash_dir:
            return Path(self.trash_dir)
        return self.input_path / ".copycat-trash"


def get_settings() -> Settings:
    """Read effective settings from the DB (falling back to defaults)."""
    # Imported lazily to avoid a circular import at module load time.
    from .db import get_all_settings

    raw = {**DEFAULTS, **get_all_settings()}
    return Settings(
        input_dir=raw["input_dir"],
        trash_dir=raw["trash_dir"],
        delete_mode=raw["delete_mode"],
        frames_per_strip=int(raw["frames_per_strip"]),
        thumb_width=int(raw["thumb_width"]),
        similarity_threshold=float(raw["similarity_threshold"]),
        duration_tolerance=float(raw["duration_tolerance"]),
        match_method=raw["match_method"],
        match_ignore_duration=str(raw["match_ignore_duration"]).lower() in ("1", "true", "yes", "on"),
    )
