import json
import subprocess
from pathlib import Path

import pytest

from e2dm2.models import (
    ClipSelection,
    ExportSize,
    SelectionType,
    WorkflowMode,
    validate_clip_selections,
)
from e2dm2.project import (
    create_project,
    delete_project,
    import_media,
    load_project,
    move_media,
    recent_projects,
    remember_project,
    save_project,
)


def make_video(path: Path, color: str = "blue", duration: float = 0.25) -> None:
    result = subprocess.run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
        "-i", f"color=c={color}:s=320x180:r=30:d={duration}", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
    ], capture_output=True)
    assert result.returncode == 0


def test_project_round_trip_and_media_import(tmp_path):
    original = tmp_path / "original.mp4"
    make_video(original)
    project = create_project("Coastal Flight", tmp_path / "projects")
    imported = import_media(project.path, project.settings, [original])
    assert original.is_file()
    assert len(imported) == 1
    assert imported[0].resolve(project.path).is_file()
    project.settings.workflow = WorkflowMode.FULL_LENGTH
    project.settings.exports = [ExportSize.SOURCE, ExportSize.HD_1080]
    save_project(project.path, project.settings)
    loaded = load_project(project.path)
    assert loaded.settings.name == "Coastal Flight"
    assert loaded.settings.workflow == WorkflowMode.FULL_LENGTH
    assert loaded.settings.exports == [ExportSize.SOURCE, ExportSize.HD_1080]
    assert loaded.settings.media[0].width == 320


def test_import_cleans_partial_file_on_cancellation(tmp_path):
    original = tmp_path / "original.mp4"
    make_video(original)
    project = create_project("Cancelled", tmp_path / "projects")
    from e2dm2.models import CancellationToken
    token = CancellationToken()
    token.cancel()
    assert import_media(project.path, project.settings, [original], cancellation=token) == []
    assert list((project.path / "source").glob("*.partial")) == []


def test_move_media_changes_project_order(tmp_path):
    project = create_project("Order", tmp_path / "projects")
    one, two = tmp_path / "one.mp4", tmp_path / "two.mp4"
    make_video(one, "red")
    make_video(two, "green")
    import_media(project.path, project.settings, [one, two])
    move_media(project.settings, 1, 0)
    assert [item.original_name for item in project.settings.media] == ["two.mp4", "one.mp4"]


def test_clip_selections_round_trip_with_millisecond_precision(tmp_path):
    project = create_project("Marks", tmp_path / "projects")
    source = tmp_path / "marked.mp4"
    make_video(source, duration=1.0)
    import_media(project.path, project.settings, [source])
    project.settings.media[0].selections = [
        ClipSelection(SelectionType.EXCLUDE, 25, 125),
        ClipSelection(SelectionType.REQUIRED, 200, 900),
    ]
    save_project(project.path, project.settings)

    loaded = load_project(project.path)
    assert loaded.settings.schema_version == 2
    assert loaded.settings.media[0].selections == project.settings.media[0].selections
    data = json.loads((project.path / "project.json").read_text(encoding="utf-8"))
    assert data["media"][0]["selections"][0] == {"type": "exclude", "start_ms": 25, "end_ms": 125}


def test_version_one_project_migrates_with_empty_selections(tmp_path):
    project = create_project("Legacy", tmp_path / "projects")
    data = json.loads((project.path / "project.json").read_text(encoding="utf-8"))
    data["schema_version"] = 1
    data["media"] = [{
        "relative_path": "source/old.mp4", "original_name": "old.mp4", "width": 320, "height": 180,
        "fps": 30, "duration": 2, "codec": "h264", "size_bytes": 100,
    }]
    (project.path / "project.json").write_text(json.dumps(data), encoding="utf-8")
    loaded = load_project(project.path)
    assert loaded.settings.schema_version == 2
    assert loaded.settings.media[0].selections == []


def test_selection_validation_limits_and_overlap_rules():
    touching = [
        ClipSelection(SelectionType.EXCLUDE, 0, 1000),
        ClipSelection(SelectionType.REQUIRED, 1000, 21_000),
    ]
    assert validate_clip_selections(touching, 30) == touching
    with pytest.raises(ValueError, match="20 seconds"):
        validate_clip_selections([ClipSelection(SelectionType.REQUIRED, 0, 20_001)], 30)
    with pytest.raises(ValueError, match="overlap"):
        validate_clip_selections([
            ClipSelection(SelectionType.EXCLUDE, 0, 1001),
            ClipSelection(SelectionType.REQUIRED, 1000, 2000),
        ], 30)
    with pytest.raises(ValueError, match="within"):
        validate_clip_selections([ClipSelection(SelectionType.EXCLUDE, 0, 30_001)], 30)


def test_delete_project_removes_folder_and_recent_entry(tmp_path):
    project = create_project("Disposable", tmp_path / "projects")
    recent_root = tmp_path / "state"
    remember_project(project.path, recent_root)
    assert recent_projects(recent_root) == [project.path]

    delete_project(project.path, recent_root)
    assert not project.path.exists()
    assert recent_projects(recent_root) == []


def test_delete_project_rejects_non_project_folder(tmp_path):
    ordinary_folder = tmp_path / "ordinary"
    ordinary_folder.mkdir()
    (ordinary_folder / "keep.txt").write_text("keep", encoding="utf-8")
    with pytest.raises(ValueError, match="not a valid"):
        delete_project(ordinary_folder, tmp_path / "state")
    assert (ordinary_folder / "keep.txt").is_file()
