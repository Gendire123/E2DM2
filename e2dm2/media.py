from __future__ import annotations

import json
import subprocess
from fractions import Fraction
from pathlib import Path

from .models import MediaItem


VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v"}


def parse_fps(value: str | None) -> float:
    if not value or value == "0/0":
        return 0.0
    try:
        return float(Fraction(value))
    except (ValueError, ZeroDivisionError):
        return 0.0


def probe_media(path: Path, relative_path: str | None = None) -> MediaItem:
    command = [
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=width,height,codec_name,avg_frame_rate,r_frame_rate",
        "-show_entries", "format=duration,size", "-of", "json", str(path),
    ]
    result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode != 0:
        raise ValueError(f"FFprobe could not read {path.name}: {result.stderr.strip()}")
    try:
        data = json.loads(result.stdout)
        stream = data["streams"][0]
        fmt = data["format"]
        fps = parse_fps(stream.get("avg_frame_rate")) or parse_fps(stream.get("r_frame_rate"))
        return MediaItem(
            relative_path=relative_path or path.name,
            original_name=path.name,
            width=int(stream["width"]),
            height=int(stream["height"]),
            fps=fps,
            duration=float(fmt["duration"]),
            codec=str(stream.get("codec_name", "unknown")),
            size_bytes=int(fmt.get("size", path.stat().st_size)),
        )
    except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError(f"FFprobe returned incomplete metadata for {path.name}") from exc


def group_media(media: list[MediaItem]) -> dict[str, list[MediaItem]]:
    groups: dict[str, list[MediaItem]] = {}
    for item in media:
        groups.setdefault(item.group_key, []).append(item)
    return groups


def fit_within_1080(width: int, height: int) -> tuple[int, int]:
    scale = min(1.0, 1920 / max(width, 1), 1080 / max(height, 1))
    target_width = max(2, int(width * scale) // 2 * 2)
    target_height = max(2, int(height * scale) // 2 * 2)
    return target_width, target_height

