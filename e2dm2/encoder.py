from __future__ import annotations

import re
import logging
import subprocess
from dataclasses import dataclass


LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class EncoderInfo:
    codec: str
    display_name: str
    hardware: bool


ENCODER_CANDIDATES = (
    EncoderInfo("h264_amf", "AMD AMF", True),
    EncoderInfo("h264_nvenc", "NVIDIA NVENC", True),
    EncoderInfo("h264_qsv", "Intel Quick Sync", True),
    EncoderInfo("libx264", "CPU x264", False),
)


def listed_encoders() -> set[str]:
    import os
    creationflags = 0x08000000 if os.name == "nt" else 0
    result = subprocess.run(
        ["ffmpeg", "-hide_banner", "-encoders"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=creationflags,
    )
    if result.returncode != 0:
        raise RuntimeError("FFmpeg is unavailable or could not list encoders.")
    return set(re.findall(r"^\s*[A-Z.]{6}\s+(\S+)", result.stdout, re.MULTILINE))


def probe_encoder(encoder: EncoderInfo, timeout: float = 12.0) -> bool:
    command = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
        "-i", "color=c=black:s=128x128:r=30:d=0.15", "-an", "-c:v", encoder.codec,
        "-frames:v", "3", "-f", "null", "-",
    ]
    try:
        import os
        creationflags = 0x08000000 if os.name == "nt" else 0
        success = subprocess.run(command, capture_output=True, timeout=timeout, creationflags=creationflags).returncode == 0
        LOGGER.info("Encoder probe %s: %s", encoder.display_name, "available" if success else "unavailable")
        return success
    except (OSError, subprocess.TimeoutExpired):
        LOGGER.exception("Encoder probe failed for %s", encoder.display_name)
        return False


def select_encoder(test_hardware: bool = True) -> EncoderInfo:
    available = listed_encoders()
    for encoder in ENCODER_CANDIDATES:
        if encoder.codec not in available:
            LOGGER.debug("Encoder is not listed by FFmpeg: %s", encoder.codec)
            continue
        if not test_hardware or probe_encoder(encoder):
            LOGGER.info("Selected encoder: %s (%s)", encoder.display_name, encoder.codec)
            return encoder
    raise RuntimeError("No usable H.264 encoder was found in this FFmpeg installation.")


def encoder_arguments(codec: str, bitrate_kbps: int) -> list[str]:
    rate = f"{bitrate_kbps}k"
    peak = f"{round(bitrate_kbps * 1.25)}k"
    common = ["-b:v", rate, "-maxrate", peak, "-bufsize", f"{bitrate_kbps * 2}k"]
    if codec == "h264_amf":
        return ["-c:v", codec, "-quality", "quality", "-rc", "vbr_peak", *common]
    if codec == "h264_nvenc":
        return ["-c:v", codec, "-preset", "p6", "-rc", "vbr", *common]
    if codec == "h264_qsv":
        return ["-c:v", codec, "-preset", "slow", *common]
    return ["-c:v", "libx264", "-preset", "slow", *common]
