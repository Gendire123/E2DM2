from __future__ import annotations

import os
import sys
from pathlib import Path


def bundled_tool_directory() -> Path | None:
    """Return the packaged FFmpeg directory when running a standalone build."""
    executable_root = Path(sys.executable).resolve().parent
    package_root = Path(__file__).resolve().parent
    candidates = (
        executable_root / "bin",
        package_root.parent / "bin",
        package_root / "bin",
    )
    suffix = ".exe" if os.name == "nt" else ""
    for candidate in candidates:
        if (candidate / f"ffmpeg{suffix}").is_file() and (candidate / f"ffprobe{suffix}").is_file():
            return candidate
    return None


def configure_bundled_tools() -> Path | None:
    """Put packaged media tools first on PATH for subprocess and QProcess calls."""
    tool_directory = bundled_tool_directory()
    if tool_directory is None:
        return None

    tool_path = str(tool_directory)
    current_entries = os.environ.get("PATH", "").split(os.pathsep)
    remaining_entries = [entry for entry in current_entries if entry and entry.casefold() != tool_path.casefold()]
    os.environ["PATH"] = os.pathsep.join((tool_path, *remaining_entries))
    return tool_directory
