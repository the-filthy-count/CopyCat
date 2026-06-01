"""ffprobe wrapper: extract container/stream metadata."""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class ProbeResult:
    duration: Optional[float] = None
    width: Optional[int] = None
    height: Optional[int] = None
    codec: Optional[str] = None
    fps: Optional[float] = None
    bitrate: Optional[int] = None


def _parse_fps(rate: str) -> Optional[float]:
    # ffprobe reports frame rates as fractions like "30000/1001".
    try:
        num, _, den = rate.partition("/")
        den_val = float(den) if den else 1.0
        if den_val == 0:
            return None
        return round(float(num) / den_val, 3)
    except (ValueError, TypeError):
        return None


def probe(path: Path) -> ProbeResult:
    cmd = [
        "ffprobe", "-v", "quiet",
        "-print_format", "json",
        "-show_format", "-show_streams",
        str(path),
    ]
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if out.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {out.stderr.strip()[:500]}")

    data = json.loads(out.stdout or "{}")
    fmt = data.get("format", {})
    streams = data.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)

    result = ProbeResult()
    if fmt.get("duration"):
        try:
            result.duration = round(float(fmt["duration"]), 3)
        except ValueError:
            pass
    if fmt.get("bit_rate"):
        try:
            result.bitrate = int(fmt["bit_rate"])
        except ValueError:
            pass

    if video:
        result.width = video.get("width")
        result.height = video.get("height")
        result.codec = video.get("codec_name")
        result.fps = _parse_fps(video.get("avg_frame_rate") or video.get("r_frame_rate") or "")
        if result.duration is None and video.get("duration"):
            try:
                result.duration = round(float(video["duration"]), 3)
            except ValueError:
                pass

    return result
