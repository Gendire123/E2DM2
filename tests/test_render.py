import json
import importlib
import shutil
import subprocess
from pathlib import Path

import pytest

from e2dm2.catalog import load_song_catalog
from e2dm2.encoder import EncoderInfo, encoder_arguments
from e2dm2.models import (
    CancellationToken,
    ClipSelection,
    ExportSize,
    MediaItem,
    RenderOutputPlan,
    RenderPlan,
    RenderRequest,
    SelectionType,
    SegmentPlan,
    WorkflowMode,
)
from e2dm2.project import create_project
from e2dm2.render import create_render_plan, render


def test_create_plan_snapshots_song_and_serializes(tmp_path):
    project = create_project("Plan", tmp_path / "projects")
    source = project.path / "source" / "clip.mp4"
    source.write_bytes(b"placeholder")
    project.settings.media = [MediaItem("source/clip.mp4", "clip.mp4", 2720, 1530, 59.94, 350, "h264", 1_000_000_000)]
    request = RenderRequest(WorkflowMode.EPIC_MONTAGE, [ExportSize.SOURCE, ExportSize.QHD_1440], "epic-montage-2")
    plan = create_render_plan(
        project,
        request,
        songs=load_song_catalog(custom_root=tmp_path / "library"),
        encoder=EncoderInfo("libx264", "CPU x264", False),
    )
    assert len(plan.outputs) == 2
    assert (plan.outputs[1].width, plan.outputs[1].height) == (2560, 1440)
    assert plan.outputs[1].bitrate_kbps >= 24000
    assert plan.schema_version == 2
    assert plan.planner_version != "legacy"
    assert plan.reproducibility["input_sha256"]
    assert plan.reproducibility["deterministic_seed"]
    assert plan.qc["status"] == "pass"
    assert plan.outputs[1].qc["music_cues_aligned"] == 88
    assert Path(plan.music_path).is_file()
    assert list((project.path / "plans").glob("render-plan_*.json"))
    json.dumps(plan.to_dict())
    restored = RenderPlan.from_dict(plan.to_dict())
    assert restored.planner_version == plan.planner_version
    assert restored.reproducibility == plan.reproducibility
    assert restored.outputs[1].qc == plan.outputs[1].qc


def test_epic_two_30fps_source_delivers_5994_with_all_cues(tmp_path):
    project = create_project("Maison", tmp_path / "projects")
    source = project.path / "source" / "house.mp4"
    source.write_bytes(b"placeholder")
    project.settings.media = [MediaItem(
        "source/house.mp4", "house.mp4", 3840, 2160, 29.93836296092496,
        536.8593, "h264", 2_352_985_781,
        [ClipSelection(SelectionType.EXCLUDE, 0, 23_668)],
    )]
    plan = create_render_plan(
        project,
        RenderRequest(WorkflowMode.EPIC_MONTAGE, [ExportSize.QHD_1440], "epic-montage-2"),
        songs=load_song_catalog(custom_root=tmp_path / "library"),
        encoder=EncoderInfo("libx264", "CPU x264", False),
    )
    output = plan.outputs[0]
    assert output.fps == pytest.approx(60000 / 1001)
    assert (output.width, output.height) == (2560, 1440)
    assert output.qc["music_cues_aligned"] == output.qc["music_cues_total"] == 88
    assert output.qc["minimum_shot_frames"] >= 8
    assert output.qc["minimum_transition_source_jump_seconds"] >= 4.5
    assert output.qc["short_transition_jump_count"] == 0
    assert output.qc["maximum_crossfade_seconds"] <= 0.101


def test_encoder_arguments_cover_all_backends():
    for codec in ("h264_amf", "h264_nvenc", "h264_qsv", "libx264"):
        arguments = encoder_arguments(codec, 8000)
        assert "-c:v" in arguments
        assert "8000k" in arguments
        assert "10000k" in arguments
    assert "vbr_peak" in encoder_arguments("h264_amf", 8000)
    assert "vbr" in encoder_arguments("h264_nvenc", 8000)


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="FFmpeg is required")
def test_generated_fixture_renders_with_cpu(tmp_path):
    video = tmp_path / "input.mp4"
    audio = tmp_path / "audio.wav"
    subprocess.run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
        "-i", "color=c=blue:s=320x180:r=30:d=1", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(video),
    ], check=True)
    subprocess.run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
        "-i", "sine=frequency=440:duration=1", str(audio),
    ], check=True)
    project = tmp_path / "project"
    (project / "temp").mkdir(parents=True)
    (project / "renders").mkdir()
    destination = project / "renders" / "output.mp4"
    output = RenderOutputPlan(
        "fixture", "320x180_30fps", [str(video)], 320, 180, 30, 1,
        ExportSize.SOURCE, str(destination), 1000, [],
    )
    plan = RenderPlan(
        1, str(project), "Fixture", WorkflowMode.FULL_LENGTH, str(audio), None,
        "libx264", [output], "drone-music-3",
    )
    events = []
    result = render(plan, events.append)
    assert result.successful_outputs
    assert destination.is_file()
    assert any(event.stage == "rendering" for event in events)
    assert json.loads((tmp_path / "last-rendered-song.json").read_text(encoding="utf-8")) == {
        "schema_version": 1,
        "workflow": "full_length",
        "song_id": "drone-music-3",
    }


def test_pre_cancelled_render_does_not_start_outputs(tmp_path):
    token = CancellationToken()
    token.cancel()
    plan = RenderPlan(1, str(tmp_path), "Cancelled", WorkflowMode.FULL_LENGTH, "missing", None, "libx264", [])
    result = render(plan, cancellation_token=token)
    assert result.cancelled
    assert result.outputs == []


def test_render_plan_maps_clip_local_marks_to_group_timeline(tmp_path, monkeypatch):
    project = create_project("Marked Plan", tmp_path / "projects")
    first = project.path / "source" / "first.mp4"
    second = project.path / "source" / "second.mp4"
    first.write_bytes(b"first")
    second.write_bytes(b"second")
    project.settings.media = [
        MediaItem("source/first.mp4", "first.mp4", 1920, 1080, 30, 110, "h264", 1000),
        MediaItem(
            "source/second.mp4", "second.mp4", 1920, 1080, 30, 110, "h264", 1000,
            [
                ClipSelection(SelectionType.EXCLUDE, 0, 10_000),
                ClipSelection(SelectionType.REQUIRED, 20_000, 30_000),
            ],
        ),
    ]
    encoder = EncoderInfo("libx264", "CPU x264", False)
    montage = create_render_plan(
        project,
        RenderRequest(WorkflowMode.EPIC_MONTAGE, [ExportSize.SOURCE], "epic-montage-1"),
        songs=load_song_catalog(custom_root=tmp_path / "library"),
        encoder=encoder,
    )
    segments = montage.outputs[0].segments
    protected = [segment for segment in segments if segment.protected]
    assert len(protected) == 1
    assert (protected[0].source_start, protected[0].source_duration) == (125, 20)
    assert not any(segment.source_start < 120 and segment.source_start + segment.source_duration > 110 for segment in segments)
    assert json.loads(json.dumps(montage.to_dict()))["outputs"][0]["segments"][0]["protected"] in {True, False}

    audio = tmp_path / "music.wav"
    audio.write_bytes(b"audio")
    render_module = importlib.import_module("e2dm2.render")
    monkeypatch.setattr(render_module, "_snapshot_full_track", lambda *_: audio)
    full = create_render_plan(
        project,
        RenderRequest(WorkflowMode.FULL_LENGTH, [ExportSize.SOURCE]),
        encoder=encoder,
    )
    assert full.outputs[0].duration_seconds == pytest.approx(210)
    assert [(segment.source_start, segment.source_duration) for segment in full.outputs[0].segments] == [
        (0, 110), (120, 100),
    ]


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="FFmpeg is required")
def test_full_length_exclusion_filter_renders_selected_intervals(tmp_path):
    video = tmp_path / "marked-input.mp4"
    audio = tmp_path / "marked-audio.wav"
    subprocess.run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
        "-i", "testsrc2=s=320x180:r=30:d=2", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(video),
    ], check=True)
    subprocess.run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
        "-i", "sine=frequency=440:duration=2", str(audio),
    ], check=True)
    project = tmp_path / "marked-project"
    (project / "temp").mkdir(parents=True)
    (project / "renders").mkdir()
    destination = project / "renders" / "marked.mp4"
    segments = [
        SegmentPlan(0, 0, 0.5, 0.5, 1, "natural", 1, False, False, 0, 0.5, 0),
        SegmentPlan(1, 1, 1, 1, 1, "natural", 1, False, False, 0.5, 1, 0),
    ]
    output = RenderOutputPlan(
        "marked", "320x180_30fps", [str(video)], 320, 180, 30, 1.5,
        ExportSize.SOURCE, str(destination), 1000, segments,
    )
    plan = RenderPlan(1, str(project), "Marked", WorkflowMode.FULL_LENGTH, str(audio), None, "libx264", [output])
    result = render(plan)
    assert result.successful_outputs
    probe = subprocess.run([
        "ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(destination),
    ], capture_output=True, text=True, check=True)
    assert float(probe.stdout.strip()) == pytest.approx(1.5, abs=0.1)
