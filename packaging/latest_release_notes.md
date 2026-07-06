E2DM2 v1.0.9 fixes a production error that could happen after using the paint tools to exclude unwanted sections from multiple clips.

## Fixed: false "Marked footage ranges overlap" error

Some projects could fail during production with an error like:

```text
3840x2160_29.97fps: Marked footage ranges overlap.
```

This could happen even when the user checked the painted Exclude sections and none of them visibly overlapped.

## What was happening

E2DM2 lets users paint sections of each clip as Exclude or Required. Those painted ranges are stored in milliseconds because that is what the timeline editor works with.

Video files, however, often have durations with fractional milliseconds. For example, a clip might really be `10.0006` seconds long, while the painted timeline can store the end of that clip as `10.001` seconds.

When E2DM2 prepared the final render, it combined all clips from the same output group into one internal timeline. That tiny rounding difference could make an Exclude range at the end of one clip appear to overlap with an Exclude range at the start of the next clip.

Example:

```text
Clip 1 actual end:       10.0006 seconds
Clip 1 painted exclude:  ends at 10.0010 seconds
Clip 2 starts at:        10.0006 seconds
Clip 2 painted exclude:  starts immediately
```

To the user, these ranges are on different clips and do not overlap. Internally, the first range extended a fraction of a millisecond past the clip boundary, so the render planner rejected the project.

## How it was fixed

E2DM2 now clamps each painted range to the real duration of its own source clip before building the combined render timeline.

That means:

- an Exclude range painted to the end of a clip now stops exactly at that clip's real end;
- it can no longer spill into the next clip by a fraction of a millisecond;
- projects with many clips and painted exclusions should no longer fail with a false overlap error at production time.

This fix applies to existing projects. Users do not need to re-import footage or repaint their excluded sections.

## Download and Installation

1. Download `E2DM2-Setup-1.0.9.exe` from the assets section below.
2. Double-click the installer and follow the on-screen instructions.
3. The installer can replace an earlier E2DM2 version while preserving existing projects and user-created media.
4. After installation, open **Help > About E2DM2** to confirm that version 1.0.9 is running.
