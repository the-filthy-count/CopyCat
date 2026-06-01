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
# input_dirs is a newline/comma separated list of folders to scan.
DEFAULTS: dict[str, str] = {
    "input_dirs": os.environ.get("INPUT_DIRS") or os.environ.get("INPUT_DIR", "/media"),
    # Name of the trash subfolder created inside each input dir (per-directory trash).
    "trash_dirname": os.environ.get("TRASH_DIRNAME", ".copycat-trash"),
    "delete_mode": os.environ.get("DELETE_MODE", "trash"),  # trash | permanent
    "thumb_width": os.environ.get("THUMB_WIDTH", "240"),
    "similarity_threshold": os.environ.get("SIMILARITY_THRESHOLD", "0.15"),
    "duration_tolerance": os.environ.get("DURATION_TOLERANCE", "2"),
    # combined | phash | dhash | ahash | whash
    "match_method": os.environ.get("MATCH_METHOD", "combined"),
    # "1" -> match on visuals regardless of runtime (catches trimmed copies)
    "match_ignore_duration": os.environ.get("MATCH_IGNORE_DURATION", "1"),
    # "1" -> scan sub-folders recursively, "0" -> only the top-level folder
    "recursive": os.environ.get("RECURSIVE", "1"),
}

# Number of filmstrip stills per video (fixed).
FRAMES_PER_STRIP = 10


@dataclass
class Settings:
    input_dirs: str            # newline/comma separated list of folders
    trash_dirname: str         # trash subfolder name created inside each input dir
    delete_mode: str
    frames_per_strip: int
    thumb_width: int
    similarity_threshold: float
    duration_tolerance: float
    match_method: str
    match_ignore_duration: bool
    recursive: bool

    @property
    def input_dir_list(self) -> list[str]:
        out = []
        for chunk in self.input_dirs.replace(",", "\n").splitlines():
            c = chunk.strip()
            if c:
                out.append(c)
        return out

    @property
    def input_paths(self) -> list[Path]:
        return [Path(p) for p in self.input_dir_list]

    @property
    def input_path(self) -> Path:
        """Primary input dir (first)."""
        paths = self.input_paths
        return paths[0] if paths else Path("/media")

    def trash_path_for(self, input_dir: Path) -> Path:
        """Per-directory trash folder for a given input directory."""
        return Path(input_dir) / self.trash_dirname

    @property
    def trash_paths(self) -> list[Path]:
        """Every input directory's trash folder."""
        return [self.trash_path_for(p) for p in self.input_paths]


def get_settings() -> Settings:
    """Read effective settings from the DB (falling back to defaults)."""
    # Imported lazily to avoid a circular import at module load time.
    from .db import get_all_settings

    raw = {**DEFAULTS, **get_all_settings()}
    return Settings(
        input_dirs=raw["input_dirs"],
        trash_dirname=raw["trash_dirname"],
        delete_mode=raw["delete_mode"],
        frames_per_strip=FRAMES_PER_STRIP,
        thumb_width=int(raw["thumb_width"]),
        similarity_threshold=float(raw["similarity_threshold"]),
        duration_tolerance=float(raw["duration_tolerance"]),
        match_method=raw["match_method"],
        match_ignore_duration=str(raw["match_ignore_duration"]).lower() in ("1", "true", "yes", "on"),
        recursive=str(raw["recursive"]).lower() in ("1", "true", "yes", "on"),
    )
