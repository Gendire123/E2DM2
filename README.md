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

## Song Library

Built-in presets live under `e2dm2/assets/songs`. Custom presets created by the library editor live under `Documents\E2DM2\Library`. Each song folder contains its audio file and a versioned `preset.json`; projects copy a snapshot of both for reproducible renders.

The alpha entitlement provider unlocks the preset editor. A future licensing provider can gate the `preset_editor` feature without changing the editor or manifest format.
