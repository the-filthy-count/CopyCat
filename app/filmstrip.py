"""Extract evenly-spaced still frames into per-video thumbnail JPEGs."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import List, Optional

from . import config


def thumb_dir_for(video_id: int) -> Path:
    return config.THUMBS_DIR / str(video_id)


def _extract_frame(src: Path, timestamp: float, dest: Path, width: int) -> bool:
    """Grab a single frame at ``timestamp`` seconds, scaled to ``width`` px."""
    cmd = [
        "ffmpeg", "-nostdin", "-y",
        "-ss", f"{max(timestamp, 0):.3f}",
        "-i", str(src),
        "-frames:v", "1",
        "-vf", f"scale={width}:-2",
        "-q:v", "3",
        str(dest),
    ]
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    return out.returncode == 0 and dest.exists() and dest.stat().st_size > 0


def extract_filmstrip(
    video_id: int,
    src: Path,
    duration: Optional[float],
    frames: int,
    width: int,
) -> List[Path]:
    """Extract up to ``frames`` thumbnails; returns the written file paths.

    Frames are sampled at the midpoint of evenly-sized time slices so the very
    first/last (often black) frames are avoided. Falls back to a single frame
    when duration is unknown.
    """
    dest_dir = thumb_dir_for(video_id)
    if dest_dir.exists():
        shutil.rmtree(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)

    written: List[Path] = []

    if not duration or duration <= 0:
        dest = dest_dir / "frame_000.jpg"
        if _extract_frame(src, 0.0, dest, width):
            written.append(dest)
        return written

    n = max(frames, 1)
    for i in range(n):
        # Midpoint of slice i -> spreads samples across the whole duration.
        ts = duration * (i + 0.5) / n
        dest = dest_dir / f"frame_{i:03d}.jpg"
        if _extract_frame(src, ts, dest, width):
            written.append(dest)

    return written
