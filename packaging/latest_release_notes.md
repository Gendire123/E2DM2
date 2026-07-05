E2DM2 v1.0.7 fixes incorrect "not enough footage" warnings for variable-frame-rate videos and prevents a quality-control error when producing an approved shortened montage.

## What Was Fixed

### Variable-frame-rate clips now stay together

Some drones record at a nominal frame rate such as 29.97 fps while reporting a slightly different average for every clip. E2DM2 previously rounded those raw averages to two decimal places and treated each result as a separate output group.

For example, a project containing more than 12 minutes of 1920x1080 footage could report clips at 29.41, 29.42, and 29.43 fps. Although all of the clips came from the same recording format, E2DM2 split them into three groups. Two groups contained only about 2:49 and 2:54 of footage, so the application warned that there was not enough material for a 3:47 song even though the complete project had plenty.

E2DM2 now recognizes these small variations as variable-frame-rate measurements of the same standard recording cadence. In this example, the clips are grouped together as 29.97 fps footage and used as one source pool. The complete 12+ minutes are available to the montage planner, producing one full-length 3:47 edit without the incorrect shortage warning.

This correction is applied when a project is planned, so existing projects benefit automatically. The clips do not need to be removed and imported again.

### "Proceed and Fade Out" no longer fails quality control

When footage really is shorter than a soundtrack, E2DM2 can preserve the song's cuts and effects for as long as possible and fade out the shortened result. In one tight, fragmented source layout, the planner attempted to preserve a dissolve by reducing an intentional source jump to approximately 4.40 seconds. Quality control correctly rejected that plan because intentional jumps must be at least 4.5 seconds, resulting in this error:

> Shortened montage QC failed: 1 long cut(s) use an ambiguous source jump below 4.5s

The planner now keeps the 4.5-second quality requirement intact. If clip boundaries leave insufficient room for a safe intentional jump, E2DM2 removes the weakest optional dissolve and uses a continuous cut instead. The shortened montage can then be produced and faded out without violating its editing rules.

## Technical Improvements

- Normalizes small variable-frame-rate differences to common recording cadences before grouping footage.
- Uses the normalized cadence for consistent montage delivery timing.
- Prevents fragmented clips from silently shrinking intentional source jumps below the quality-control threshold.
- Falls back to a clean continuous cut when an optional dissolve cannot be placed safely.
- Adds regression coverage for both mixed 29.4x fps clips and shortened montages split across source files.

## Download & Installation

1. Download `E2DM2-Setup-1.0.7.exe` from the assets section below.
2. Double-click the installer.
3. Follow the on-screen instructions. The installer can replace an earlier E2DM2 version while keeping your projects available.
