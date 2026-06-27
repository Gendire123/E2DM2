from __future__ import annotations

import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable

from .catalog import default_project_root
from .media import VIDEO_EXTENSIONS, probe_media
from .models import CancellationToken, MediaItem, Project, ProjectSettings


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def slugify(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "-", value).strip("-").lower()
    return slug or "drone-project"


def create_project(name: str, root: Path | None = None) -> Project:
    root = root or default_project_root()
    root.mkdir(parents=True, exist_ok=True)
    base = root / f"{datetime.now():%Y-%m-%d}_{slugify(name)}"
    project_path = base
    counter = 2
    while project_path.exists():
        project_path = Path(f"{base}_{counter}")
        counter += 1
    for folder in ("source", "music", "renders", "temp", "plans"):
        (project_path / folder).mkdir(parents=True, exist_ok=True)
    now = _now()
    settings = ProjectSettings(schema_version=1, name=name.strip() or "Drone Project", created_at=now, updated_at=now)
    save_project(project_path, settings)
    remember_project(project_path)
    return Project(project_path, settings)


def save_project(project_path: Path, settings: ProjectSettings) -> None:
    settings.updated_at = _now()
    target = project_path / "project.json"
    temporary = target.with_suffix(".json.partial")
    temporary.write_text(json.dumps(settings.to_dict(), indent=2), encoding="utf-8")
    temporary.replace(target)


def load_project(project_path: Path) -> Project:
    path = project_path / "project.json" if project_path.is_dir() else project_path
    data = json.loads(path.read_text(encoding="utf-8"))
    settings = ProjectSettings.from_dict(data)
    remember_project(path.parent)
    return Project(path.parent, settings)


def _unique_destination(folder: Path, name: str) -> Path:
    candidate = folder / name
    counter = 2
    while candidate.exists() or candidate.with_suffix(candidate.suffix + ".partial").exists():
        candidate = folder / f"{Path(name).stem}_{counter}{Path(name).suffix}"
        counter += 1
    return candidate


def import_media(
    project_path: Path,
    settings: ProjectSettings,
    sources: Iterable[Path],
    progress: Callable[[int, int, str], None] | None = None,
    cancellation: CancellationToken | None = None,
) -> list[MediaItem]:
    candidates = [path for path in sources if path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS]
    total_bytes = sum(path.stat().st_size for path in candidates)
    free_bytes = shutil.disk_usage(project_path).free
    if total_bytes > free_bytes:
        raise OSError(f"Not enough disk space. Need {total_bytes:,} bytes; {free_bytes:,} bytes are available.")
    imported: list[MediaItem] = []
    copied = 0
    for source in candidates:
        if cancellation and cancellation.cancelled:
            break
        destination = _unique_destination(project_path / "source", source.name)
        partial = destination.with_suffix(destination.suffix + ".partial")
        try:
            with source.open("rb") as input_file, partial.open("wb") as output_file:
                while chunk := input_file.read(8 * 1024 * 1024):
                    if cancellation and cancellation.cancelled:
                        raise InterruptedError("Import cancelled")
                    output_file.write(chunk)
                    copied += len(chunk)
                    if progress:
                        progress(copied, total_bytes, source.name)
            if partial.stat().st_size != source.stat().st_size:
                raise OSError(f"Copied size does not match for {source.name}")
            partial.replace(destination)
            item = probe_media(destination, f"source/{destination.name}")
            imported.append(item)
            settings.media.append(item)
            save_project(project_path, settings)
        except Exception:
            partial.unlink(missing_ok=True)
            raise
    return imported


def remove_media(settings: ProjectSettings, index: int) -> MediaItem:
    return settings.media.pop(index)


def move_media(settings: ProjectSettings, old_index: int, new_index: int) -> None:
    if old_index == new_index or not 0 <= old_index < len(settings.media):
        return
    new_index = max(0, min(new_index, len(settings.media) - 1))
    settings.media.insert(new_index, settings.media.pop(old_index))


def remember_project(project_path: Path, root: Path | None = None) -> None:
    root = root or default_project_root()
    root.mkdir(parents=True, exist_ok=True)
    state_path = root / "recent.json"
    recent: list[str] = []
    if state_path.exists():
        try:
            recent = list(json.loads(state_path.read_text(encoding="utf-8")))
        except (OSError, ValueError, TypeError):
            recent = []
    value = str(project_path.resolve())
    recent = [value, *(item for item in recent if item != value and Path(item).exists())][:10]
    temporary = state_path.with_suffix(".json.partial")
    temporary.write_text(json.dumps(recent, indent=2), encoding="utf-8")
    temporary.replace(state_path)


def recent_projects(root: Path | None = None) -> list[Path]:
    state_path = (root or default_project_root()) / "recent.json"
    if not state_path.exists():
        return []
    try:
        return [Path(item) for item in json.loads(state_path.read_text(encoding="utf-8")) if Path(item).exists()]
    except (OSError, ValueError, TypeError):
        return []
