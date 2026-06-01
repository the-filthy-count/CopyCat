"""SQLModel tables: Video, Setting, ScanRun."""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from sqlmodel import Field, SQLModel


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Status(str, Enum):
    pending = "pending"
    processing = "processing"
    done = "done"
    error = "error"


class State(str, Enum):
    active = "active"      # present in the library
    trashed = "trashed"    # moved to the trash folder, restorable
    deleted = "deleted"    # permanently removed from disk


class Video(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    path: str = Field(index=True, unique=True)
    original_path: Optional[str] = None  # pre-trash location, for accurate restore
    filename: str = ""

    # Identity / change detection.
    size: int = 0
    mtime: float = 0.0
    sha256: Optional[str] = Field(default=None, index=True)

    # Probed metadata.
    duration: Optional[float] = None
    width: Optional[int] = None
    height: Optional[int] = None
    codec: Optional[str] = None
    fps: Optional[float] = None
    bitrate: Optional[int] = None

    # Perceptual fingerprint: JSON list of hex pHash strings (one per frame).
    phash_signature: Optional[str] = None
    thumb_count: int = 0

    # Queue + lifecycle.
    status: Status = Field(default=Status.pending, index=True)
    state: State = Field(default=State.active, index=True)
    error: Optional[str] = None

    # Grouping.
    group_id: Optional[int] = Field(default=None, index=True)
    pinned_out: bool = False  # "not a duplicate" -> excluded from regrouping

    created_at: datetime = Field(default_factory=utcnow)
    processed_at: Optional[datetime] = None


class Setting(SQLModel, table=True):
    key: str = Field(primary_key=True)
    value: str = ""


class ScanRun(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    started_at: datetime = Field(default_factory=utcnow)
    finished_at: Optional[datetime] = None
    discovered: int = 0   # new/changed files enqueued
    seen: int = 0         # total files walked
