from __future__ import annotations

import threading
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class WorkflowMode(str, Enum):
    FULL_LENGTH = "full_length"
    EPIC_MONTAGE = "epic_montage"


class ExportSize(str, Enum):
    SOURCE = "source"
    HD_1080 = "1080p"


class EnergyLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass(slots=True)
class MediaItem:
    relative_path: str
    original_name: str
    width: int
    height: int
    fps: float
    duration: float
    codec: str
    size_bytes: int

    @property
    def group_key(self) -> str:
        fps_bucket = round(self.fps, 2)
        return f"{self.width}x{self.height}_{fps_bucket:g}fps"

    def resolve(self, project_path: Path) -> Path:
        return project_path / self.relative_path


@dataclass(slots=True)
class TransitionSettings:
    duration_seconds: float = 0.25
    hard_cut_threshold_seconds: float = 2.0


@dataclass(slots=True)
class SourceProgressionSettings:
    short_cut_threshold_seconds: float = 5.0
    short_cut_advance_seconds: float = 1.0


@dataclass(slots=True)
class DarkCue:
    start_seconds: float
    end_seconds: float
    fade_out_seconds: float = 1.0
    opacity: float = 0.8


@dataclass(slots=True)
class FlashCue:
    start_seconds: float
    duration_seconds: float = 1.0
    fade_in_seconds: float = 0.35
    opacity: float = 0.9


@dataclass(slots=True)
class HeartbeatSettings:
    timestamps: list[float] = field(default_factory=list)
    opacity: float = 0.2
    fade_seconds: float = 0.45


@dataclass(slots=True)
class SongManifest:
    schema_version: int
    song_id: str
    title: str
    artist: str
    audio_file: str
    moods: list[str]
    bpm: float | None
    energy: EnergyLevel
    total_duration_seconds: float
    minimum_source_duration_seconds: float
    opening_fade_seconds: float
    cuts_end_seconds: float
    fade_out_seconds: float
    escalation_seconds: float
    cut_timestamps: list[float]
    transitions: TransitionSettings = field(default_factory=TransitionSettings)
    source_progression: SourceProgressionSettings = field(default_factory=SourceProgressionSettings)
    heartbeat: HeartbeatSettings = field(default_factory=HeartbeatSettings)
    dark_cue: DarkCue | None = None
    flash_cue: FlashCue | None = None
    effects: list[str] = field(default_factory=list)
    readonly: bool = False
    manifest_path: Path | None = field(default=None, repr=False, compare=False)

    @property
    def audio_path(self) -> Path:
        if self.manifest_path is None:
            return Path(self.audio_file)
        return self.manifest_path.parent / self.audio_file

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data.pop("manifest_path", None)
        data["energy"] = self.energy.value
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any], manifest_path: Path | None = None, readonly: bool = False) -> "SongManifest":
        cut_timestamps = [float(value) for value in data["cut_timestamps"]]
        effects_data = data.get("effects")
        if effects_data is None:
            effects = ["none"] * len(cut_timestamps)
            # Upgrade heartbeat
            hb_timestamps = data.get("heartbeat", {}).get("timestamps", [])
            for ts in hb_timestamps:
                for idx, cut_ts in enumerate(cut_timestamps):
                    if abs(cut_ts - ts) < 0.01:
                        effects[idx] = "heartbeat"
            # Upgrade flash cue
            flash_start = data.get("flash_cue", {}).get("start_seconds") if data.get("flash_cue") else None
            if flash_start is not None:
                for idx, cut_ts in enumerate(cut_timestamps):
                    if abs(cut_ts - flash_start) < 0.01:
                        effects[idx] = "flash"
            # Upgrade dark cue (slow_fade_out)
            dark_start = data.get("dark_cue", {}).get("start_seconds") if data.get("dark_cue") else None
            if dark_start is not None:
                for idx, cut_ts in enumerate(cut_timestamps):
                    if abs(cut_ts - dark_start) < 0.01:
                        effects[idx] = "slow_fade_out"
        else:
            effects = [str(val) for val in effects_data]
            if len(effects) < len(cut_timestamps):
                effects = effects + ["none"] * (len(cut_timestamps) - len(effects))
            elif len(effects) > len(cut_timestamps):
                effects = effects[:len(cut_timestamps)]

        return cls(
            schema_version=int(data.get("schema_version", 1)),
            song_id=str(data["song_id"]),
            title=str(data["title"]),
            artist=str(data.get("artist", "Unknown")),
            audio_file=str(data["audio_file"]),
            moods=[str(value) for value in data.get("moods", [])],
            bpm=float(data["bpm"]) if data.get("bpm") is not None else None,
            energy=EnergyLevel(data.get("energy", EnergyLevel.MEDIUM.value)),
            total_duration_seconds=float(data["total_duration_seconds"]),
            minimum_source_duration_seconds=float(data["minimum_source_duration_seconds"]),
            opening_fade_seconds=float(data.get("opening_fade_seconds", 0)),
            cuts_end_seconds=float(data["cuts_end_seconds"]),
            fade_out_seconds=float(data["fade_out_seconds"]),
            escalation_seconds=float(data.get("escalation_seconds", 0)),
            cut_timestamps=cut_timestamps,
            transitions=TransitionSettings(**data.get("transitions", {})),
            source_progression=SourceProgressionSettings(**data.get("source_progression", {})),
            heartbeat=HeartbeatSettings(**data.get("heartbeat", {})),
            dark_cue=DarkCue(**data["dark_cue"]) if data.get("dark_cue") else None,
            flash_cue=FlashCue(**data["flash_cue"]) if data.get("flash_cue") else None,
            effects=effects,
            readonly=readonly or bool(data.get("readonly", False)),
            manifest_path=manifest_path,
        )


@dataclass(slots=True)
class ProjectSettings:
    schema_version: int
    name: str
    created_at: str
    updated_at: str
    media: list[MediaItem] = field(default_factory=list)
    workflow: WorkflowMode = WorkflowMode.EPIC_MONTAGE
    song_id: str | None = "epic-montage-1"
    full_length_track_id: str = "drone-music-1"
    exports: list[ExportSize] = field(default_factory=lambda: [ExportSize.SOURCE])

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["workflow"] = WorkflowMode(self.workflow).value
        data["exports"] = [ExportSize(value).value for value in self.exports]
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ProjectSettings":
        return cls(
            schema_version=int(data.get("schema_version", 1)),
            name=str(data["name"]),
            created_at=str(data["created_at"]),
            updated_at=str(data["updated_at"]),
            media=[MediaItem(**item) for item in data.get("media", [])],
            workflow=WorkflowMode(data.get("workflow", WorkflowMode.EPIC_MONTAGE.value)),
            song_id=data.get("song_id"),
            full_length_track_id=str(data.get("full_length_track_id", "drone-music-1")),
            exports=[ExportSize(value) for value in data.get("exports", [ExportSize.SOURCE.value])],
        )


@dataclass(slots=True)
class Project:
    path: Path
    settings: ProjectSettings


@dataclass(slots=True)
class RenderRequest:
    workflow: WorkflowMode
    exports: list[ExportSize]
    song_id: str | None = None
    full_length_track_id: str = "drone-music-1"


@dataclass(slots=True)
class SegmentPlan:
    index: int
    source_start: float
    source_duration: float
    output_duration: float
    speed: float
    style: str
    zoom: float
    motion_blur: bool
    cue: bool
    visible_start: float
    visible_duration: float
    transition_after: float


@dataclass(slots=True)
class RenderOutputPlan:
    output_id: str
    group_key: str
    media_paths: list[str]
    width: int
    height: int
    fps: float
    duration_seconds: float
    export_size: ExportSize
    output_path: str
    bitrate_kbps: int
    segments: list[SegmentPlan] = field(default_factory=list)


@dataclass(slots=True)
class RenderPlan:
    schema_version: int
    project_path: str
    project_name: str
    workflow: WorkflowMode
    music_path: str
    song_manifest: dict[str, Any] | None
    encoder: str
    outputs: list[RenderOutputPlan]

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["workflow"] = self.workflow.value
        for output in data["outputs"]:
            output["export_size"] = output["export_size"].value
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RenderPlan":
        outputs = []
        for output in data.get("outputs", []):
            output_data = dict(output)
            output_data["export_size"] = ExportSize(output_data["export_size"])
            output_data["segments"] = [SegmentPlan(**segment) for segment in output_data.get("segments", [])]
            outputs.append(RenderOutputPlan(**output_data))
        return cls(
            schema_version=int(data.get("schema_version", 1)),
            project_path=str(data["project_path"]),
            project_name=str(data["project_name"]),
            workflow=WorkflowMode(data["workflow"]),
            music_path=str(data["music_path"]),
            song_manifest=data.get("song_manifest"),
            encoder=str(data["encoder"]),
            outputs=outputs,
        )


@dataclass(slots=True)
class ProgressEvent:
    stage: str
    message: str
    output_id: str | None = None
    percent: float | None = None


@dataclass(slots=True)
class OutputResult:
    output_id: str
    output_path: str
    success: bool
    error: str | None = None


@dataclass(slots=True)
class RenderResult:
    outputs: list[OutputResult]
    cancelled: bool = False

    @property
    def successful_outputs(self) -> list[OutputResult]:
        return [result for result in self.outputs if result.success]


class CancellationToken:
    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()
