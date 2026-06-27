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

## Footage Marking

Select an imported clip and choose **Preview / Edit**, or double-click the clip. Drag on the full-video timeline with the red tool to exclude footage or the green tool to require an uncut segment. Required ranges are limited to 20 seconds. Saved markings are restored with the project and are enforced by every production workflow.

The first time a clip is opened, E2DM2 builds a low-resolution, all-keyframe preview in the background. The original remains available while it is prepared, and later preview sessions reuse the cached proxy for substantially faster timeline hovering.

## Song Library

Built-in presets live under `e2dm2/assets/songs`. Custom presets created by the library editor live under `Documents\E2DM2\Library`. Each song folder contains its audio file and a versioned `preset.json`; projects copy a snapshot of both for reproducible renders.

The alpha entitlement provider unlocks the preset editor. A future licensing provider can gate the `preset_editor` feature without changing the editor or manifest format.
