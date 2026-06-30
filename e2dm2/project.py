from __future__ import annotations

import json
import logging
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable

from .catalog import default_project_root
from .media import VIDEO_EXTENSIONS, probe_media
from .models import CancellationToken, MediaItem, Project, ProjectSettings, WorkflowMode


LOGGER = logging.getLogger(__name__)
LAST_RENDERED_SONG_FILE = "last-rendered-song.json"
DEFAULT_SONG_ID = "epic-montage-1"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def slugify(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "-", value).strip("-").lower()
    return slug or "drone-project"


def remember_rendered_song(project_path: Path, workflow: WorkflowMode, song_id: str) -> None:
    """Persist the soundtrack from a render that produced at least one output."""
    state_path = project_path.parent / LAST_RENDERED_SONG_FILE
    temporary = state_path.with_suffix(".json.partial")
    temporary.write_text(json.dumps({
        "schema_version": 1,
        "workflow": WorkflowMode(workflow).value,
        "song_id": song_id,
    }, indent=2), encoding="utf-8")
    temporary.replace(state_path)


def last_rendered_song(root: Path) -> tuple[WorkflowMode, str] | None:
    state_path = root / LAST_RENDERED_SONG_FILE
    if not state_path.is_file():
        return None
    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
        song_id = str(data["song_id"]).strip()
        if not song_id:
            return None
        return WorkflowMode(data["workflow"]), song_id
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        LOGGER.warning("Ignoring invalid last rendered song state: %s", state_path)
        return None


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
    settings = ProjectSettings(schema_version=2, name=name.strip() or "Drone Project", created_at=now, updated_at=now)
    previous_song = last_rendered_song(root)
    if previous_song:
        workflow, song_id = previous_song
        settings.workflow = workflow
        if workflow == WorkflowMode.FULL_LENGTH:
            settings.full_length_track_id = song_id
        else:
            settings.song_id = song_id
    else:
        settings.song_id = DEFAULT_SONG_ID
    save_project(project_path, settings)
    remember_project(project_path)
    LOGGER.info("Created project '%s' at %s", settings.name, project_path)
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
    LOGGER.info("Opened project '%s' from %s", settings.name, path.parent)
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
    LOGGER.info("Import requested: %d file(s), %.2f GB", len(candidates), total_bytes / 1024 ** 3)
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
        LOGGER.info("Copying %s to %s", source, destination)
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
            LOGGER.info(
                "Imported %s | %dx%d | %.3f fps | %.3f seconds | %s",
                destination.name, item.width, item.height, item.fps, item.duration, item.codec,
            )
            imported.append(item)
            settings.media.append(item)
            save_project(project_path, settings)
        except Exception:
            partial.unlink(missing_ok=True)
            LOGGER.exception("Import failed for %s", source)
            raise
    LOGGER.info("Import completed: %d file(s)", len(imported))
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


def forget_project(project_path: Path, root: Path | None = None) -> None:
    state_path = (root or default_project_root()) / "recent.json"
    if not state_path.exists():
        return
    try:
        removed = project_path.resolve()
        recent = [
            item for item in json.loads(state_path.read_text(encoding="utf-8"))
            if Path(item).resolve() != removed and Path(item).exists()
        ]
    except (OSError, ValueError, TypeError):
        recent = []
    temporary = state_path.with_suffix(".json.partial")
    temporary.write_text(json.dumps(recent, indent=2), encoding="utf-8")
    temporary.replace(state_path)


def delete_project(project_path: Path, recent_root: Path | None = None) -> None:
    path = project_path.parent if project_path.is_file() and project_path.name == "project.json" else project_path
    resolved = path.resolve()
    if resolved.parent == resolved or resolved == Path.home().resolve():
        raise ValueError("Refusing to delete an unsafe project path.")
    if not (resolved / "project.json").is_file():
        raise ValueError("The selected folder is not a valid E2DM2 project.")
    shutil.rmtree(resolved)
    forget_project(resolved, recent_root)
    LOGGER.info("Deleted project folder: %s", resolved)
