from __future__ import annotations

import json
import logging
import math
import os
import re
import shutil
import subprocess
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Callable

from .catalog import find_song, full_length_track, load_song_catalog
from .encoder import EncoderInfo, encoder_arguments, select_encoder
from .media import fit_within_1080, group_media
from .models import (
    CancellationToken,
    ExportSize,
    OutputResult,
    ProgressEvent,
    Project,
    RenderOutputPlan,
    RenderPlan,
    RenderRequest,
    RenderResult,
    SegmentPlan,
    SongManifest,
    WorkflowMode,
)
from .montage import build_montage_segment_plan, validate_forward_progression


ProgressCallback = Callable[[ProgressEvent], None]
LOGGER = logging.getLogger(__name__)


def _notify(callback: ProgressCallback | None, event: ProgressEvent) -> None:
    if callback:
        callback(event)


def _safe_name(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_-]+", "_", value).strip("_")
    return cleaned or "Drone_Project"


def _fps_value(fps: float) -> str:
    if abs(fps - 29.97) < 0.05:
        return "30000/1001"
    if abs(fps - 59.94) < 0.05:
        return "60000/1001"
    return f"{fps:.3f}" if fps > 0 else "30"


def _bitrate_limits(width: int, height: int, fps: float) -> tuple[int, int]:
    pixels = width * height
    if pixels >= 8_000_000:
        return (25000, 60000) if fps > 50 else (18000, 45000)
    if pixels >= 3_500_000:
        return (16000, 40000) if fps > 50 else (12000, 30000)
    if pixels >= 1_900_000:
        return (8000, 22000) if fps > 50 else (6000, 16000)
    return 3000, 10000


def _target_bitrate(media, width: int, height: int, fps: float) -> int:
    duration = sum(item.duration for item in media)
    if duration <= 0:
        return 25000
    original_kbps = sum(item.size_bytes for item in media) * 8 / duration / 1000
    minimum, maximum = _bitrate_limits(width, height, fps)
    return max(minimum, min(maximum, int(original_kbps * 0.35)))


def _copy_snapshot(source: Path, destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and destination.stat().st_size == source.stat().st_size:
        return destination
    partial = destination.with_suffix(destination.suffix + ".partial")
    shutil.copy2(source, partial)
    partial.replace(destination)
    return destination


def _snapshot_epic_song(project: Project, song: SongManifest) -> tuple[Path, dict]:
    folder = project.path / "music" / song.song_id
    audio = _copy_snapshot(song.audio_path, folder / song.audio_path.name)
    data = song.to_dict()
    data["audio_file"] = audio.name
    data["readonly"] = True
    manifest_path = folder / "preset.json"
    temporary = manifest_path.with_suffix(".json.partial")
    temporary.write_text(json.dumps(data, indent=2), encoding="utf-8")
    temporary.replace(manifest_path)
    return audio, data


def _snapshot_full_track(project: Project, track_id: str) -> Path:
    track = full_length_track(track_id)
    if not track.path.is_file():
        raise FileNotFoundError(f"Soundtrack not found: {track.path}")
    return _copy_snapshot(track.path, project.path / "music" / "full-length" / track.path.name)


def create_render_plan(
    project: Project,
    request: RenderRequest,
    songs: list[SongManifest] | None = None,
    encoder: EncoderInfo | None = None,
) -> RenderPlan:
    if not project.settings.media:
        raise ValueError("Import at least one video before rendering.")
    for item in project.settings.media:
        if not item.resolve(project.path).is_file():
            raise FileNotFoundError(f"Project source is missing: {item.relative_path}")
    encoder = encoder or select_encoder()
    LOGGER.info(
        "Creating render plan | project=%s | workflow=%s | exports=%s | encoder=%s",
        project.settings.name, request.workflow.value, [value.value for value in request.exports], encoder.codec,
    )
    song_data: dict | None = None
    song: SongManifest | None = None
    if request.workflow == WorkflowMode.EPIC_MONTAGE:
        if not request.song_id:
            raise ValueError("Choose an Epic song before rendering.")
        song = find_song(request.song_id, songs or load_song_catalog())
        music_path, song_data = _snapshot_epic_song(project, song)
    else:
        music_path = _snapshot_full_track(project, request.full_length_track_id)

    if not request.exports:
        raise ValueError("Choose at least one export size.")
    outputs: list[RenderOutputPlan] = []
    stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    for group_key, media in group_media(project.settings.media).items():
        source_width, source_height, fps = media[0].width, media[0].height, media[0].fps
        source_duration = sum(item.duration for item in media)
        segments: list[SegmentPlan] = []
        if song:
            if source_duration < song.minimum_source_duration_seconds:
                raise ValueError(
                    f"{song.title} needs at least {song.minimum_source_duration_seconds:.1f} seconds "
                    f"of {group_key} footage; this project has {source_duration:.1f} seconds."
                )
            segments = build_montage_segment_plan(source_duration, song)
            progression_errors = validate_forward_progression(
                segments,
                song.source_progression.short_cut_advance_seconds,
                song.source_progression.short_cut_threshold_seconds,
            )
            if progression_errors:
                raise ValueError(" ".join(progression_errors))
        for export_size in dict.fromkeys(request.exports):
            if export_size == ExportSize.HD_1080:
                width, height = fit_within_1080(source_width, source_height)
            else:
                width, height = source_width, source_height
            mode_label = song.song_id if song else "full-length"
            output_id = f"{group_key}-{mode_label}-{export_size.value}"
            output_name = f"{stamp}_{_safe_name(project.settings.name)}_{mode_label}_{group_key}_{export_size.value}.mp4"
            outputs.append(RenderOutputPlan(
                output_id=output_id,
                group_key=group_key,
                media_paths=[str(item.resolve(project.path)) for item in media],
                width=width,
                height=height,
                fps=fps,
                duration_seconds=song.total_duration_seconds if song else source_duration,
                export_size=export_size,
                output_path=str(project.path / "renders" / output_name),
                bitrate_kbps=_target_bitrate(media, width, height, fps),
                segments=segments,
            ))
    plan = RenderPlan(
        schema_version=1,
        project_path=str(project.path),
        project_name=project.settings.name,
        workflow=request.workflow,
        music_path=str(music_path),
        song_manifest=song_data,
        encoder=encoder.codec,
        outputs=outputs,
    )
    plan_path = project.path / "plans" / f"render-plan_{stamp}.json"
    temporary = plan_path.with_suffix(".json.partial")
    temporary.write_text(json.dumps(plan.to_dict(), indent=2), encoding="utf-8")
    temporary.replace(plan_path)
    LOGGER.info("Saved render plan with %d output(s): %s", len(outputs), plan_path)
    return plan


def _write_concat(paths: list[str], destination: Path) -> None:
    lines = []
    for value in paths:
        escaped = str(Path(value).resolve()).replace("\\", "/").replace("'", "\\'")
        lines.append(f"file '{escaped}'")
    destination.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _zoom_filter(width: int, height: int, zoom: float) -> str | None:
    if zoom <= 1:
        return None
    zoom_width = int(round(width * zoom / 2) * 2)
    zoom_height = int(round(height * zoom / 2) * 2)
    return f"scale={zoom_width}:{zoom_height},crop={width}:{height}"


def _montage_filter(output: RenderOutputPlan, song: SongManifest) -> str:
    source_width = int(output.group_key.split("x", 1)[0])
    source_height = int(output.group_key.split("x", 1)[1].split("_", 1)[0])
    fps = _fps_value(output.fps)
    split_labels = [f"[v{segment.index}]" for segment in output.segments]
    filters = [f"[0:v]split={len(split_labels)}{''.join(split_labels)}"]
    for segment in output.segments:
        chain = [
            f"[v{segment.index}]trim=start={segment.source_start:.6f}:duration={segment.source_duration:.6f}",
            f"setpts=(PTS-STARTPTS)/{segment.speed:.6f}", f"fps={fps}", "settb=AVTB",
        ]
        zoom = _zoom_filter(source_width, source_height, segment.zoom)
        if zoom:
            chain.append(zoom)
        if segment.style == "sepia":
            chain.append("colorchannelmixer=rr=.393:rg=.769:rb=.189:gr=.349:gg=.686:gb=.168:br=.272:bg=.534:bb=.131")
        if segment.motion_blur:
            chain.append("tmix=frames=3:weights='1 2 1'")
        chain.extend(["setsar=1", "format=yuv420p"])
        filters.append(",".join(chain) + f"[s{segment.index}]")

    current_label = "s0"
    current_duration = output.segments[0].output_duration
    for segment in output.segments[1:]:
        previous = output.segments[segment.index - 1]
        label = f"x{segment.index}"
        if previous.transition_after > 0:
            offset = max(current_duration - previous.transition_after, 0)
            filters.append(
                f"[{current_label}][s{segment.index}]xfade=transition=fade:"
                f"duration={previous.transition_after:.6f}:offset={offset:.6f},settb=AVTB[{label}]"
            )
        else:
            filters.append(f"[{current_label}][s{segment.index}]concat=n=2:v=1:a=0,settb=AVTB[{label}]")
        current_duration += segment.output_duration - previous.transition_after
        current_label = label

    filters.append(
        f"[{current_label}]fade=t=in:st=0:d={song.opening_fade_seconds:.6f},"
        f"fade=t=out:st={song.cuts_end_seconds:.6f}:d={song.fade_out_seconds:.6f},"
        f"format=yuv420p[basevideo]"
    )
    video_label = "basevideo"
    if song.dark_cue:
        cue = song.dark_cue
        end = cue.end_seconds + cue.fade_out_seconds
        filters.append(
            f"color=c=black@{cue.opacity:.3f}:s={source_width}x{source_height}:d={song.total_duration_seconds:.6f},"
            f"format=yuva420p,fade=t=in:st={cue.start_seconds:.6f}:d={cue.end_seconds - cue.start_seconds:.6f}:alpha=1,"
            f"fade=t=out:st={cue.end_seconds:.6f}:d={cue.fade_out_seconds:.6f}:alpha=1[darkcue]"
        )
        filters.append(f"[{video_label}][darkcue]overlay=shortest=1:enable='between(t\\,{cue.start_seconds:.6f}\\,{end:.6f})'[darkvideo]")
        video_label = "darkvideo"
    for index, timestamp in enumerate(song.heartbeat.timestamps):
        end = timestamp + song.heartbeat.fade_seconds
        filters.append(
            f"color=c=black@{song.heartbeat.opacity:.3f}:s={source_width}x{source_height}:d={song.total_duration_seconds:.6f},"
            f"format=yuva420p,fade=t=out:st={timestamp:.6f}:d={song.heartbeat.fade_seconds:.6f}:alpha=1[heartbeat{index}]"
        )
        filters.append(
            f"[{video_label}][heartbeat{index}]overlay=shortest=1:enable='between(t\\,{timestamp:.6f}\\,{end:.6f})',"
            f"format=yuv420p[heartbeatvideo{index}]"
        )
        video_label = f"heartbeatvideo{index}"
    if song.flash_cue:
        cue = song.flash_cue
        fade_out_start = cue.start_seconds + cue.fade_in_seconds
        end = cue.start_seconds + cue.duration_seconds
        filters.append(
            f"color=c=white@{cue.opacity:.3f}:s={source_width}x{source_height}:d={song.total_duration_seconds:.6f},"
            f"format=yuva420p,fade=t=in:st={cue.start_seconds:.6f}:d={cue.fade_in_seconds:.6f}:alpha=1,"
            f"fade=t=out:st={fade_out_start:.6f}:d={end - fade_out_start:.6f}:alpha=1[whiteflash]"
        )
        filters.append(f"[{video_label}][whiteflash]overlay=shortest=1:enable='between(t\\,{cue.start_seconds:.6f}\\,{end:.6f})'[effectvideo]")
        video_label = "effectvideo"
    filters.append(f"[{video_label}]scale={output.width}:{output.height}:flags=lanczos,setsar=1,format=yuv420p[videoout]")
    music_fade_start = song.total_duration_seconds - song.fade_out_seconds
    filters.append(
        f"[1:a]atrim=start=0:duration={song.total_duration_seconds:.6f},asetpts=N/SR/TB,"
        f"afade=t=out:st={music_fade_start:.6f}:d={song.fade_out_seconds:.6f},"
        "aformat=sample_rates=48000:channel_layouts=stereo[musicout]"
    )
    return ";\n".join(filters)


def _full_length_command(plan: RenderPlan, output: RenderOutputPlan, concat: Path, temporary: Path) -> list[str]:
    fade_in = min(3.0, output.duration_seconds / 3)
    fade_out = min(8.0, output.duration_seconds / 3)
    fade_out_start = max(output.duration_seconds - fade_out, 0)
    audio_fade_in = min(5.0, output.duration_seconds / 3)
    audio_fade_out = min(10.0, output.duration_seconds / 3)
    audio_fade_start = max(output.duration_seconds - audio_fade_out, 0)
    video_filter = (
        f"fade=t=in:st=0:d={fade_in:.3f},fade=t=out:st={fade_out_start:.3f}:d={fade_out:.3f},"
        f"scale={output.width}:{output.height}:flags=lanczos,setsar=1,format=yuv420p"
    )
    audio_filter = (
        f"[1:a]atrim=0:{output.duration_seconds:.6f},asetpts=N/SR/TB,"
        f"afade=t=in:st=0:d={audio_fade_in:.3f},afade=t=out:st={audio_fade_start:.3f}:d={audio_fade_out:.3f}[musicout]"
    )
    return [
        "ffmpeg", "-hide_banner", "-y", "-fflags", "+genpts", "-f", "concat", "-safe", "0", "-i", str(concat),
        "-stream_loop", "-1", "-i", plan.music_path, "-map", "0:v:0", "-vf", video_filter,
        "-filter_complex", audio_filter, "-map", "[musicout]", "-sn", "-dn", "-r", _fps_value(output.fps),
        *encoder_arguments(plan.encoder, output.bitrate_kbps), "-profile:v", "high", "-g", str(max(1, round(output.fps * 2))),
        "-c:a", "aac", "-b:a", "192k", "-t", f"{output.duration_seconds:.6f}", "-shortest",
        "-avoid_negative_ts", "make_zero", "-movflags", "+faststart", "-progress", "pipe:1", "-nostats", str(temporary),
    ]


def _montage_command(plan: RenderPlan, output: RenderOutputPlan, concat: Path, filter_path: Path, temporary: Path) -> list[str]:
    return [
        "ffmpeg", "-hide_banner", "-y", "-fflags", "+genpts", "-analyzeduration", "200M", "-probesize", "200M",
        "-f", "concat", "-safe", "0", "-i", str(concat), "-stream_loop", "-1", "-i", plan.music_path,
        "-filter_complex_script", str(filter_path), "-map", "[videoout]", "-map", "[musicout]", "-sn", "-dn",
        "-t", f"{output.duration_seconds:.6f}", "-r", _fps_value(output.fps),
        *encoder_arguments(plan.encoder, output.bitrate_kbps), "-profile:v", "high", "-g", str(max(1, round(output.fps * 2))),
        "-c:a", "aac", "-b:a", "192k", "-shortest", "-avoid_negative_ts", "make_zero", "-movflags", "+faststart",
        "-progress", "pipe:1", "-nostats", str(temporary),
    ]


def _run_ffmpeg(
    command: list[str], output: RenderOutputPlan, cancellation: CancellationToken, progress: ProgressCallback | None,
) -> tuple[bool, str | None]:
    creation_flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    LOGGER.info("Starting FFmpeg for %s", output.output_id)
    LOGGER.debug("FFmpeg command: %s", subprocess.list2cmdline(command))
    process = subprocess.Popen(
        command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
        creationflags=creation_flags,
    )
    log_lines: list[str] = []
    assert process.stdout is not None
    while True:
        line = process.stdout.readline()
        if line:
            line = line.strip()
            log_lines.append(line)
            log_lines = log_lines[-30:]
            LOGGER.debug("ffmpeg[%s] %s", output.output_id, line)
            if line.startswith(("out_time_us=", "out_time_ms=")):
                try:
                    elapsed = int(line.split("=", 1)[1]) / 1_000_000
                    percent = min(100.0, elapsed / max(output.duration_seconds, 0.001) * 100)
                    _notify(progress, ProgressEvent("rendering", f"Rendering {output.output_id}", output.output_id, percent))
                except ValueError:
                    pass
        if cancellation.cancelled and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
        if process.poll() is not None and not line:
            break
    if cancellation.cancelled:
        LOGGER.warning("FFmpeg cancelled for %s", output.output_id)
        return False, "Cancelled"
    if process.returncode != 0:
        LOGGER.error("FFmpeg failed for %s with exit code %s", output.output_id, process.returncode)
        return False, "\n".join(log_lines[-12:]) or f"FFmpeg exited with code {process.returncode}"
    LOGGER.info("FFmpeg completed for %s", output.output_id)
    return True, None


def render(
    plan: RenderPlan,
    progress_callback: ProgressCallback | None = None,
    cancellation_token: CancellationToken | None = None,
) -> RenderResult:
    cancellation = cancellation_token or CancellationToken()
    project_path = Path(plan.project_path)
    temp_root = project_path / "temp"
    temp_root.mkdir(parents=True, exist_ok=True)
    results: list[OutputResult] = []
    song = SongManifest.from_dict(plan.song_manifest) if plan.song_manifest else None
    for index, output in enumerate(plan.outputs):
        if cancellation.cancelled:
            break
        _notify(progress_callback, ProgressEvent("preparing", f"Preparing {output.output_id}", output.output_id, 0))
        token = f"{datetime.now():%Y%m%d%H%M%S}_{index}"
        concat = temp_root / f"concat_{token}.txt"
        filter_path = temp_root / f"filter_{token}.txt"
        temporary = temp_root / f"render_{token}.tmp.mp4"
        destination = Path(output.output_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        _write_concat(output.media_paths, concat)
        try:
            if plan.workflow == WorkflowMode.EPIC_MONTAGE:
                if song is None:
                    raise ValueError("Epic render plan is missing its song manifest.")
                filter_path.write_text(_montage_filter(output, song), encoding="utf-8")
                command = _montage_command(plan, output, concat, filter_path, temporary)
            else:
                command = _full_length_command(plan, output, concat, temporary)
            success, error = _run_ffmpeg(command, output, cancellation, progress_callback)
            if success:
                if destination.exists():
                    stem, suffix, counter = destination.stem, destination.suffix, 2
                    while destination.exists():
                        destination = destination.with_name(f"{stem}_{counter}{suffix}")
                        counter += 1
                temporary.replace(destination)
                LOGGER.info("Created render: %s", destination)
                _notify(progress_callback, ProgressEvent("complete", f"Created {destination.name}", output.output_id, 100))
                results.append(OutputResult(output.output_id, str(destination), True))
            else:
                temporary.unlink(missing_ok=True)
                results.append(OutputResult(output.output_id, str(destination), False, error))
        except Exception as exc:
            temporary.unlink(missing_ok=True)
            LOGGER.exception("Render output failed: %s", output.output_id)
            results.append(OutputResult(output.output_id, str(destination), False, str(exc)))
        finally:
            concat.unlink(missing_ok=True)
            filter_path.unlink(missing_ok=True)
    return RenderResult(results, cancelled=cancellation.cancelled)
