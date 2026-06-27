from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .models import SongManifest


PACKAGE_ROOT = Path(__file__).resolve().parent
REPOSITORY_ROOT = PACKAGE_ROOT.parent
BUILTIN_SONG_ROOT = PACKAGE_ROOT / "assets" / "songs"


@dataclass(frozen=True, slots=True)
class FullLengthTrack:
    track_id: str
    title: str
    description: str
    path: Path


FULL_LENGTH_TRACKS = (
    FullLengthTrack("drone-music-1", "Relaxing Piano", "Piano, relaxing, easy listening", REPOSITORY_ROOT / "dronemusic1.m4a"),
    FullLengthTrack("drone-music-2", "Interstellar Theme", "Expansive cinematic theme", REPOSITORY_ROOT / "dronemusic2.m4a"),
    FullLengthTrack("drone-music-3", "Inception Theme", "Dramatic cinematic theme", REPOSITORY_ROOT / "dronemusic3.m4a"),
    FullLengthTrack("drone-music-4", "Relaxing Strings", "Calm orchestral strings", REPOSITORY_ROOT / "dronemusic4.m4a"),
)


def default_project_root() -> Path:
    override = os.environ.get("E2DM2_HOME")
    return Path(override) if override else Path.home() / "Documents" / "E2DM2"


def custom_library_root(project_root: Path | None = None) -> Path:
    return (project_root or default_project_root()) / "Library"


def validate_song_manifest(song: SongManifest, require_audio: bool = True) -> list[str]:
    errors: list[str] = []
    if song.schema_version != 1:
        errors.append(f"Unsupported schema version: {song.schema_version}")
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", song.song_id):
        errors.append("Song ID must contain lowercase letters, numbers, and single hyphens only.")
    if not song.title.strip():
        errors.append("Title is required.")
    if require_audio and not song.audio_path.is_file():
        errors.append(f"Audio file does not exist: {song.audio_path}")
    if song.total_duration_seconds <= 0:
        errors.append("Total duration must be greater than zero.")
    if song.minimum_source_duration_seconds < song.total_duration_seconds:
        errors.append("Minimum source duration cannot be shorter than the montage duration.")
    if not song.cut_timestamps or abs(song.cut_timestamps[0]) > 0.000001:
        errors.append("Cut timestamps must begin at 0.")
    if song.cut_timestamps != sorted(song.cut_timestamps):
        errors.append("Cut timestamps must be sorted.")
    if len(song.cut_timestamps) != len(set(song.cut_timestamps)):
        errors.append("Cut timestamps must be unique.")
    if any(value < 0 or value >= song.total_duration_seconds for value in song.cut_timestamps):
        errors.append("Every cut timestamp must be inside the montage duration.")
    if not 0 <= song.cuts_end_seconds <= song.total_duration_seconds:
        errors.append("Fade start must be inside the montage duration.")
    if song.cuts_end_seconds + song.fade_out_seconds > song.total_duration_seconds + 0.001:
        errors.append("Fade out extends beyond the montage duration.")
    if song.transitions.duration_seconds < 0 or song.transitions.hard_cut_threshold_seconds < 0:
        errors.append("Transition values cannot be negative.")
    if song.source_progression.short_cut_advance_seconds < 0:
        errors.append("Source advance cannot be negative.")
    if any(value < 0 or value >= song.total_duration_seconds for value in song.heartbeat.timestamps):
        errors.append("Heartbeat timestamps must be inside the montage duration.")
    if not 0 <= song.heartbeat.opacity <= 1:
        errors.append("Heartbeat opacity must be between 0 and 1.")
    if song.dark_cue:
        if not 0 <= song.dark_cue.start_seconds < song.dark_cue.end_seconds <= song.total_duration_seconds:
            errors.append("Dark cue must be inside the montage duration and end after it starts.")
        if not 0 <= song.dark_cue.opacity <= 1:
            errors.append("Dark cue opacity must be between 0 and 1.")
    if song.flash_cue:
        if not 0 <= song.flash_cue.start_seconds < song.total_duration_seconds:
            errors.append("Flash cue must start inside the montage duration.")
        if song.flash_cue.start_seconds + song.flash_cue.duration_seconds > song.total_duration_seconds:
            errors.append("Flash cue extends beyond the montage duration.")
        if not 0 <= song.flash_cue.opacity <= 1:
            errors.append("Flash opacity must be between 0 and 1.")
    return errors


def probe_audio_duration(path: Path) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        raise ValueError(f"FFprobe could not read the audio file: {path}")
    try:
        return float(result.stdout.strip())
    except ValueError as exc:
        raise ValueError(f"FFprobe did not return an audio duration for: {path}") from exc


def load_song_manifest(path: Path, readonly: bool = False) -> SongManifest:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        song = SongManifest.from_dict(data, manifest_path=path, readonly=readonly)
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Could not load song manifest {path}: {exc}") from exc
    errors = validate_song_manifest(song)
    if errors:
        raise ValueError(f"Invalid song manifest {path}: {'; '.join(errors)}")
    return song


def _manifest_paths(root: Path) -> Iterable[Path]:
    if not root.exists():
        return ()
    return sorted(root.glob("*/preset.json"), key=lambda value: value.parent.name.lower())


def load_song_catalog(custom_root: Path | None = None) -> list[SongManifest]:
    songs: list[SongManifest] = []
    seen: set[str] = set()
    for path, readonly in [
        *((path, True) for path in _manifest_paths(BUILTIN_SONG_ROOT)),
        *((path, False) for path in _manifest_paths(custom_root or custom_library_root())),
    ]:
        song = load_song_manifest(path, readonly=readonly)
        if song.song_id in seen:
            raise ValueError(f"Duplicate song ID in catalog: {song.song_id}")
        seen.add(song.song_id)
        songs.append(song)
    return songs


def find_song(song_id: str, songs: Iterable[SongManifest]) -> SongManifest:
    for song in songs:
        if song.song_id == song_id:
            return song
    raise KeyError(f"Unknown Epic song: {song_id}")


def filter_songs(
    songs: Iterable[SongManifest],
    text: str = "",
    mood: str = "",
    energy: str = "",
    minimum_bpm: float | None = None,
    maximum_bpm: float | None = None,
    maximum_duration: float | None = None,
) -> list[SongManifest]:
    text = text.strip().casefold()
    mood = mood.strip().casefold()
    results = []
    for song in songs:
        haystack = " ".join([song.title, song.artist, *song.moods]).casefold()
        if text and text not in haystack:
            continue
        if mood and mood not in {value.casefold() for value in song.moods}:
            continue
        if energy and song.energy.value != energy:
            continue
        if minimum_bpm is not None and (song.bpm is None or song.bpm < minimum_bpm):
            continue
        if maximum_bpm is not None and (song.bpm is None or song.bpm > maximum_bpm):
            continue
        if maximum_duration is not None and song.total_duration_seconds > maximum_duration:
            continue
        results.append(song)
    return sorted(results, key=lambda song: (song.title.casefold(), song.total_duration_seconds))


def save_custom_song(song: SongManifest, audio_source: Path, library_root: Path | None = None) -> SongManifest:
    root = library_root or custom_library_root()
    destination = root / song.song_id
    preliminary_errors = validate_song_manifest(song, require_audio=False)
    if preliminary_errors:
        raise ValueError("\n".join(preliminary_errors))
    if any(path.parent.name == song.song_id for path in _manifest_paths(BUILTIN_SONG_ROOT)):
        raise ValueError(f"Song ID is reserved by a built-in preset: {song.song_id}")
    target_manifest = destination / "preset.json"
    if target_manifest.exists() and (song.manifest_path is None or song.manifest_path.resolve() != target_manifest.resolve()):
        raise ValueError(f"A custom song already uses this ID: {song.song_id}")
    destination.mkdir(parents=True, exist_ok=True)
    audio_destination = destination / audio_source.name
    if audio_source.resolve() != audio_destination.resolve():
        partial = audio_destination.with_suffix(audio_destination.suffix + ".partial")
        shutil.copy2(audio_source, partial)
        partial.replace(audio_destination)
    song.audio_file = audio_destination.name
    song.manifest_path = target_manifest
    song.readonly = False
    errors = validate_song_manifest(song)
    if not errors:
        audio_duration = probe_audio_duration(audio_destination)
        if song.total_duration_seconds > audio_duration + 0.1:
            errors.append(
                f"Montage duration ({song.total_duration_seconds:.3f}s) exceeds the audio duration ({audio_duration:.3f}s)."
            )
    if errors:
        raise ValueError("\n".join(errors))
    temporary = song.manifest_path.with_suffix(".json.partial")
    temporary.write_text(json.dumps(song.to_dict(), indent=2), encoding="utf-8")
    temporary.replace(song.manifest_path)
    return song


def duplicate_song(song: SongManifest, song_id: str, title: str, library_root: Path | None = None) -> SongManifest:
    data = song.to_dict()
    data.update({"song_id": song_id, "title": title, "readonly": False})
    duplicate = SongManifest.from_dict(data)
    return save_custom_song(duplicate, song.audio_path, library_root)


def full_length_track(track_id: str) -> FullLengthTrack:
    for track in FULL_LENGTH_TRACKS:
        if track.track_id == track_id:
            return track
    raise KeyError(f"Unknown full-length soundtrack: {track_id}")
