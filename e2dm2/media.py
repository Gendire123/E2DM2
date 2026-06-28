from __future__ import annotations

import json
import subprocess
from fractions import Fraction
from pathlib import Path

from .models import MediaItem


VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v"}
PREVIEW_PROXY_VERSION = 1


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
    import os
    creationflags = 0x08000000 if os.name == "nt" else 0
    result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace", creationflags=creationflags)
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


def preview_proxy_path(project_path: Path, media: MediaItem) -> Path:
    source_name = Path(media.relative_path).name
    source = Path(source_name)
    identity = f"{source.stem}_{source.suffix.lstrip('.').lower()}"
    return project_path / "temp" / "previews" / f"{identity}.preview-v{PREVIEW_PROXY_VERSION}.mp4"


def preview_proxy_is_current(source: Path, proxy: Path) -> bool:
    try:
        return proxy.is_file() and proxy.stat().st_size > 0 and proxy.stat().st_mtime_ns >= source.stat().st_mtime_ns
    except OSError:
        return False


def preview_proxy_arguments(source: Path, destination: Path) -> list[str]:
    """Create a small all-keyframe proxy optimized for arbitrary seeking."""
    return [
        "-hide_banner", "-loglevel", "error", "-y", "-i", str(source),
        "-map", "0:v:0", "-map", "0:a?",
        "-vf", "scale=w='min(854,iw)':h=-2,fps=30",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "30",
        "-g", "1", "-keyint_min", "1", "-sc_threshold", "0", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "96k", "-sn", "-dn", "-movflags", "+faststart",
        "-progress", "pipe:1", "-nostats", str(destination),
    ]
