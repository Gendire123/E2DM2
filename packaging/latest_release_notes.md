E2DM2 v1.0.11 resolves a rendering failure in the video montage engine, ensuring stable source allocation.

## Fixed: Montage render failure

Fixes a bug where producing a video montage could fail with the error message:
`No forward-only contiguous source allocation satisfies the montage timeline.`

This issue occurred due to a double-scaling error in the montage layout algorithm, causing skip calculations to decay quadratically instead of linearly when fitting media within clip exclusions and boundaries. The algorithm now correctly utilizes a smooth linear scale, ensuring robust and successful montage rendering.

## Download and Installation

1. Download `E2DM2-Setup-1.0.11.exe` from the assets section below.
2. Double-click the installer and follow the on-screen instructions.
3. The installer can replace an earlier E2DM2 version while preserving existing projects and user-created media.
4. After installation, open **Help > About E2DM2** to confirm that version 1.0.11 is running.
