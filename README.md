# Easy Epic Drone Movie Maker (E2DM2)

E2DM2 is a local Windows desktop application for copying drone footage into a project and producing full-length or music-synchronized Epic montages with FFmpeg.

## Setup

FFmpeg and FFprobe must be available through `PATH`.

Double-click `Setup E2DM2.cmd` once, then use `Run E2DM2.cmd` to launch the application. The default project and custom-song library location is `Documents\E2DM2`.

The **Backend Log** dock shows imports, media probing, encoder selection, render planning, FFmpeg progress, and errors. Logs are retained in rotating files under `Documents\E2DM2\Logs` and can be opened directly from the dock.

For command-line development:

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -e ".[dev]"
.\.venv\Scripts\python -m e2dm2
```

Run tests with:

```powershell
.\.venv\Scripts\python -m pytest
```

## Windows standalone build

The release build compiles the Python modules with Nuitka, bundles Qt, the app
assets, FFmpeg, and FFprobe, then creates a per-user installer with Inno Setup.
End users do not need Python or FFmpeg installed.

Build requirements are Python 3.12, FFmpeg/FFprobe on `PATH`, and Inno Setup 6.
From PowerShell:

```powershell
.\packaging\build_windows.ps1 -Version 1.0.8
```

If the project drive has limited free space, place the compiler workspace and
installer output on another drive:

```powershell
.\packaging\build_windows.ps1 -WorkRoot D:\E2DM2-build -OutputRoot D:\E2DM2-release
```

The standalone application folder is written below `build\windows`; the final
installer is `dist\E2DM2-Setup-1.0.8.exe`. The distribution contains compiled
application code rather than the original `.py` files. As with any desktop
software delivered to a customer-controlled computer, compilation raises the
reverse-engineering barrier but cannot provide absolute source-code secrecy.
When the repository path contains non-ASCII characters, the script automatically
uses the compiler-safe temporary path `C:\E2DM2-build`.

## Footage Marking

Select an imported clip and choose **Preview / Edit**, or double-click the clip. Drag on the full-video timeline with the red tool to exclude footage or the green tool to require an uncut segment. Required ranges are limited to 20 seconds. Saved markings are restored with the project and are enforced by every production workflow.

The first time a clip is opened, E2DM2 builds a low-resolution, all-keyframe preview in the background. The original remains available while it is prepared, and later preview sessions reuse the cached proxy for substantially faster timeline hovering.

## Song Library

Built-in presets live under `e2dm2/assets/songs`. Custom presets created by the library editor live under `Documents\E2DM2\Library`. Each song folder contains its audio file and a versioned `preset.json`; projects copy a snapshot of both for reproducible renders. All features including custom song imports and source-resolution renders are 100% free and open-source under the MIT license.

## Support & License

E2DM2 is open-source software licensed under the [MIT License](LICENSE). Free code signing is provided by the [SignPath Foundation](https://signpath.org).

If you enjoy using E2DM2 and want to support ongoing development, consider buying a coffee via **Help > Buy Me a Coffee ☕** in the app or visiting [Buy Me a Coffee](https://buymeacoffee.com/e2dm2).

