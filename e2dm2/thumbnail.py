from pathlib import Path
import subprocess

THUMBNAIL_VERSION = 1

def thumbnail_path(project_path: Path, media) -> Path:
    source = Path(media.relative_path).name
    stem = Path(source).stem
    return project_path / "temp" / "thumbs" / f"{stem}.thumb-v{THUMBNAIL_VERSION}.jpg"

def thumbnail_is_current(source: Path, destination: Path) -> bool:
    try:
        return destination.is_file() and destination.stat().st_mtime_ns >= source.stat().st_mtime_ns
    except OSError:
        return False

def create_thumbnail(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel", "error",
        "-y",
        "-ss", "1",
        "-i", str(source),
        "-frames:v", "1",
        "-vf", "scale=252:-1",
        str(destination),
    ]
    import os
    creationflags = 0x08000000 if os.name == "nt" else 0
    subprocess.run(command, check=True, creationflags=creationflags)
