"""Shared Jinja2 template environment + display filters."""
from __future__ import annotations

from pathlib import Path

from fastapi.templating import Jinja2Templates

from .models import Video

TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=TEMPLATES_DIR)


def human_size(num: int | None) -> str:
    if not num:
        return "0 B"
    value = float(num)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TB"


def human_duration(seconds: float | None) -> str:
    if not seconds:
        return "—"
    total = int(seconds)
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def human_bitrate(bps: int | None) -> str:
    if not bps:
        return "—"
    return f"{bps / 1_000_000:.1f} Mbps" if bps >= 1_000_000 else f"{bps // 1000} kbps"


def resolution(video: Video) -> str:
    if video.width and video.height:
        return f"{video.width}×{video.height}"
    return "—"


def similarity_pct(distance: float | None) -> str:
    if distance is None:
        return "—"
    return f"{max(0.0, (1.0 - distance)) * 100:.0f}%"


def thumb_urls(video: Video) -> list[str]:
    return [
        f"/thumbs/{video.id}/frame_{i:03d}.jpg"
        for i in range(video.thumb_count)
    ]


templates.env.filters["human_size"] = human_size
templates.env.filters["human_duration"] = human_duration
templates.env.filters["human_bitrate"] = human_bitrate
templates.env.filters["resolution"] = resolution
templates.env.filters["similarity_pct"] = similarity_pct
templates.env.filters["thumb_urls"] = thumb_urls
