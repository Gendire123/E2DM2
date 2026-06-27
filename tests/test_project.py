import json
import subprocess
from pathlib import Path

import pytest

from e2dm2.models import ExportSize, WorkflowMode
from e2dm2.project import create_project, import_media, load_project, move_media, save_project


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

