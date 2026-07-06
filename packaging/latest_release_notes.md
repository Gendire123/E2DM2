E2DM2 v1.0.10 fixes a render failure that could happen when the selected output folder was on a different drive than the project.

## Fixed: renders to another drive

When a project was stored on one drive, such as `C:`, and the output directory was changed to another drive, such as `E:`, the final video could finish rendering but fail while being moved into the output folder.

E2DM2 now handles that case correctly, so renders can be saved to a custom output folder on another drive.

This fix applies to existing projects. Users do not need to change their project settings or re-import footage.

## Download and Installation

1. Download `E2DM2-Setup-1.0.10.exe` from the assets section below.
2. Double-click the installer and follow the on-screen instructions.
3. The installer can replace an earlier E2DM2 version while preserving existing projects and user-created media.
4. After installation, open **Help > About E2DM2** to confirm that version 1.0.10 is running.
