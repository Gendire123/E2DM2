from __future__ import annotations

import os
import sys

from e2dm2.runtime import bundled_tool_directory, configure_bundled_tools


def test_packaged_tools_are_prepended_to_path(monkeypatch, tmp_path):
    app_root = tmp_path / "application"
    tool_root = app_root / "bin"
    tool_root.mkdir(parents=True)
    suffix = ".exe" if os.name == "nt" else ""
    (tool_root / f"ffmpeg{suffix}").touch()
    (tool_root / f"ffprobe{suffix}").touch()
    monkeypatch.setattr(sys, "executable", str(app_root / f"E2DM2{suffix}"))
    monkeypatch.setenv("PATH", os.pathsep.join(("first", "second")))

    assert bundled_tool_directory() == tool_root
    assert configure_bundled_tools() == tool_root
    assert os.environ["PATH"].split(os.pathsep)[0] == str(tool_root)
