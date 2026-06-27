from __future__ import annotations

from .models import SegmentPlan, SongManifest


MINIMUM_CLIP_SECONDS = 0.1


def build_montage_segment_plan(video_duration: float, song: SongManifest) -> list[SegmentPlan]:
    segment_count = len(song.cut_timestamps)
    transition_count = segment_count - 1
    cut_times = [*song.cut_timestamps, song.total_duration_seconds]
    visible_durations = [cut_times[index + 1] - cut_times[index] for index in range(segment_count)]
    transition_durations: list[float] = []
    output_durations: list[float] = []

    for index in range(segment_count):
        if index < transition_count:
            adjacent_short = (
                visible_durations[index] < song.transitions.hard_cut_threshold_seconds
                or visible_durations[index + 1] < song.transitions.hard_cut_threshold_seconds
            )
            transition = 0.0 if adjacent_short else song.transitions.duration_seconds
        else:
            transition = 0.0
        transition_durations.append(transition)
        output_durations.append(visible_durations[index] + transition)

    if min(output_durations) < MINIMUM_CLIP_SECONDS:
        raise ValueError("Montage timing contains a clip shorter than the supported minimum.")

    visible_starts: list[float] = []
    visible_cursor = 0.0
    for index, duration in enumerate(output_durations):
        visible_starts.append(visible_cursor)
        visible_cursor += duration - transition_durations[index]

    cue_index = min(
        range(segment_count),
        key=lambda index: abs(visible_starts[index] + output_durations[index] / 2 - song.escalation_seconds),
    )
    color_styles = ["natural", "natural", "natural", "natural", "sepia", "natural", "natural", "natural", "natural", "natural"]
    speed_pattern = [1.0, 1.0, 1.0, 1.15, 1.0, 1.0, 1.0, 1.0, 1.0, 1.25, 1.0, 1.0]
    speeds = [speed_pattern[index % len(speed_pattern)] for index in range(segment_count)]
    speeds[cue_index] = min(speeds[cue_index], 1.15)
    source_durations = [output_durations[index] * speeds[index] for index in range(segment_count)]

    progression = song.source_progression
    fixed_gap_count = sum(
        1 for index in range(segment_count - 1)
        if visible_durations[index] < progression.short_cut_threshold_seconds
    )
    fixed_gap_time = fixed_gap_count * progression.short_cut_advance_seconds
    flexible_gap_count = max(segment_count - 1 - fixed_gap_count, 0)
    available_gap_time = max(video_duration - sum(source_durations) - fixed_gap_time - 0.5, 0)
    flexible_gap = available_gap_time / max(flexible_gap_count, 1)

    plan: list[SegmentPlan] = []
    source_cursor = 0.0
    for index, output_duration in enumerate(output_durations):
        source_duration = source_durations[index]
        source_end = source_cursor + source_duration
        if source_end > video_duration + 0.000001:
            raise ValueError(
                "The source footage is too short for this song's forward-only edit. "
                "Add more footage or choose a shorter montage."
            )
        plan.append(SegmentPlan(
            index=index,
            source_start=source_cursor,
            source_duration=source_duration,
            output_duration=output_duration,
            speed=speeds[index],
            style="sepia" if index < len(song.effects) and song.effects[index] == "sepia" else "natural",
            zoom=1.045 if index % 3 != 1 else 1.0,
            motion_blur=index / max(segment_count - 1, 1) > 0.45 and index % 5 == 0,
            cue=index == cue_index,
            visible_start=visible_starts[index],
            visible_duration=visible_durations[index],
            transition_after=transition_durations[index],
        ))
        if index == segment_count - 1:
            source_cursor = source_end
        elif visible_durations[index] < progression.short_cut_threshold_seconds:
            source_cursor = source_end + progression.short_cut_advance_seconds
        else:
            source_cursor = source_end + flexible_gap
    return plan


def validate_forward_progression(plan: list[SegmentPlan], short_advance: float, threshold: float) -> list[str]:
    errors: list[str] = []
    for previous, current in zip(plan, plan[1:]):
        previous_end = previous.source_start + previous.source_duration
        if current.source_start < previous_end - 0.000001:
            errors.append(f"Segments {previous.index} and {current.index} overlap.")
        if previous.visible_duration < threshold:
            gap = current.source_start - previous_end
            if abs(gap - short_advance) > 0.001:
                errors.append(f"Segment {current.index} must advance by exactly {short_advance:.3f} seconds.")
    return errors
