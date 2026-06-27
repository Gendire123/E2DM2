from __future__ import annotations

from dataclasses import dataclass

from .models import SegmentPlan, SongManifest


MINIMUM_CLIP_SECONDS = 0.1


def _build_legacy_montage_segment_plan(video_duration: float, song: SongManifest) -> list[SegmentPlan]:
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


@dataclass(slots=True)
class _Interval:
    start: float
    end: float

    @property
    def duration(self) -> float:
        return self.end - self.start


def _subtract_ranges(intervals: list[_Interval], removed: list[tuple[float, float]]) -> list[_Interval]:
    result = intervals
    for remove_start, remove_end in sorted(removed):
        updated: list[_Interval] = []
        for interval in result:
            if remove_end <= interval.start or remove_start >= interval.end:
                updated.append(interval)
                continue
            if interval.start < remove_start:
                updated.append(_Interval(interval.start, remove_start))
            if remove_end < interval.end:
                updated.append(_Interval(remove_end, interval.end))
        result = updated
    return [interval for interval in result if interval.duration >= MINIMUM_CLIP_SECONDS]


def _intersections(intervals: list[_Interval], start: float, end: float) -> list[_Interval]:
    return [
        _Interval(max(interval.start, start), min(interval.end, end))
        for interval in intervals
        if min(interval.end, end) - max(interval.start, start) >= MINIMUM_CLIP_SECONDS
    ]


class _IntervalCursor:
    def __init__(self, intervals: list[_Interval]) -> None:
        self.intervals = intervals
        self.index = 0
        self.position = intervals[0].start if intervals else 0.0

    @property
    def remaining(self) -> float:
        if self.index >= len(self.intervals):
            return 0.0
        return max(0.0, self.intervals[self.index].end - self.position) + sum(
            interval.duration for interval in self.intervals[self.index + 1:]
        )

    def take(self, duration: float) -> list[_Interval]:
        pieces: list[_Interval] = []
        remaining = duration
        while remaining > 0.000001 and self.index < len(self.intervals):
            interval = self.intervals[self.index]
            available = interval.end - self.position
            if available <= 0.000001:
                self.index += 1
                if self.index < len(self.intervals):
                    self.position = self.intervals[self.index].start
                continue
            amount = min(available, remaining)
            pieces.append(_Interval(self.position, self.position + amount))
            self.position += amount
            remaining -= amount
        if remaining > 0.00001:
            raise ValueError(f"Automatic footage is short by {remaining:.3f} seconds.")
        return pieces

    def skip(self, duration: float) -> None:
        if duration <= 0:
            return
        self.take(duration)


def _validate_constraint_ranges(
    video_duration: float,
    excluded_ranges: list[tuple[float, float]],
    required_ranges: list[tuple[float, float]],
) -> None:
    combined = sorted([(*value, "excluded") for value in excluded_ranges] + [(*value, "required") for value in required_ranges])
    previous_end = 0.0
    for start, end, _kind in combined:
        if start < -0.000001 or end > video_duration + 0.000001 or start >= end:
            raise ValueError("Marked footage contains a range outside its source clip.")
        if start < previous_end - 0.000001:
            raise ValueError("Marked footage ranges overlap.")
        previous_end = end


def _effect_for_time(song: SongManifest, timestamp: float) -> str:
    for index, cut in enumerate(song.cut_timestamps):
        if abs(cut - timestamp) < 0.00001 and index < len(song.effects):
            return song.effects[index]
    return "none"


def _build_constrained_montage_segment_plan(
    video_duration: float,
    song: SongManifest,
    excluded_ranges: list[tuple[float, float]],
    required_ranges: list[tuple[float, float]],
    source_boundaries: list[float],
) -> list[SegmentPlan]:
    _validate_constraint_ranges(video_duration, excluded_ranges, required_ranges)
    boundaries = sorted({0.0, video_duration, *(value for value in source_boundaries if 0 < value < video_duration)})
    base_intervals = [_Interval(start, end) for start, end in zip(boundaries, boundaries[1:])]
    usable = _subtract_ranges(base_intervals, excluded_ranges)
    usable_duration = sum(interval.duration for interval in usable)
    if usable_duration < song.minimum_source_duration_seconds - 0.000001:
        shortage = song.minimum_source_duration_seconds - usable_duration
        raise ValueError(f"Excluded footage leaves the group {shortage:.3f} seconds short of this song's requirement.")

    required = sorted(required_ranges)
    required_duration = sum(end - start for start, end in required)
    if required_duration > song.total_duration_seconds + 0.000001:
        shortage = required_duration - song.total_duration_seconds
        raise ValueError(f"Required footage exceeds the song by {shortage:.3f} seconds.")

    automatic = _subtract_ranges(usable, required)
    source_windows: list[tuple[float, float]] = []
    cursor = 0.0
    for start, end in required:
        source_windows.append((cursor, start))
        cursor = end
    source_windows.append((cursor, video_duration))
    auto_by_window = [_intersections(automatic, start, end) for start, end in source_windows]
    available_by_window = [sum(interval.duration for interval in intervals) for intervals in auto_by_window]
    total_automatic_source = sum(available_by_window)
    filler_duration = song.total_duration_seconds - required_duration
    if filler_duration > 0.000001 and total_automatic_source < MINIMUM_CLIP_SECONDS:
        raise ValueError(f"Automatic footage is short by {filler_duration:.3f} seconds.")

    if total_automatic_source:
        output_gaps = [filler_duration * available / total_automatic_source for available in available_by_window]
        output_gaps[-1] += filler_duration - sum(output_gaps)
        tiny_duration = sum(gap for gap in output_gaps if 0 < gap < MINIMUM_CLIP_SECONDS)
        output_gaps = [0.0 if 0 < gap < MINIMUM_CLIP_SECONDS else gap for gap in output_gaps]
        recipients = [index for index, gap in enumerate(output_gaps) if gap >= MINIMUM_CLIP_SECONDS]
        if tiny_duration and recipients:
            recipient_source = sum(available_by_window[index] for index in recipients)
            for index in recipients:
                output_gaps[index] += tiny_duration * available_by_window[index] / recipient_source
            output_gaps[recipients[-1]] += filler_duration - sum(output_gaps)
        elif tiny_duration:
            output_gaps[max(range(len(output_gaps)), key=available_by_window.__getitem__)] = filler_duration
    else:
        output_gaps = [0.0] * len(source_windows)

    protected_output: list[tuple[float, float, int]] = []
    output_cursor = 0.0
    for index, (source_start, source_end) in enumerate(required):
        output_cursor += output_gaps[index]
        protected_output.append((output_cursor, output_cursor + source_end - source_start, index))
        output_cursor += source_end - source_start

    output_boundaries = {0.0, song.total_duration_seconds}
    for timestamp in song.cut_timestamps:
        if 0 <= timestamp <= song.total_duration_seconds and not any(
            start + 0.000001 < timestamp < end - 0.000001 for start, end, _ in protected_output
        ):
            output_boundaries.add(timestamp)
    for start, end, _ in protected_output:
        output_boundaries.update((start, end))
    ordered_output = sorted(output_boundaries)

    slots: list[dict] = []
    for start, end in zip(ordered_output, ordered_output[1:]):
        if end - start < MINIMUM_CLIP_SECONDS:
            continue
        protected_index = next(
            (index for protected_start, protected_end, index in protected_output
             if start >= protected_start - 0.000001 and end <= protected_end + 0.000001),
            None,
        )
        if protected_index is not None:
            slots.append({"start": start, "visible": end - start, "protected": protected_index, "window": None})
            continue
        window_index = sum(1 for _start, protected_end, _index in protected_output if protected_end <= start + 0.000001)
        slots.append({"start": start, "visible": end - start, "protected": None, "window": window_index})

    for index, slot in enumerate(slots):
        if index == len(slots) - 1 or slot["protected"] is not None:
            transition = 0.0
        else:
            adjacent_short = (
                slot["visible"] < song.transitions.hard_cut_threshold_seconds
                or slots[index + 1]["visible"] < song.transitions.hard_cut_threshold_seconds
            )
            transition = 0.0 if adjacent_short else song.transitions.duration_seconds
        slot["transition"] = transition

    cue_slot = min(
        (index for index, slot in enumerate(slots) if slot["protected"] is None),
        key=lambda index: abs(slots[index]["start"] + slots[index]["visible"] / 2 - song.escalation_seconds),
        default=-1,
    )
    speed_pattern = [1.0, 1.0, 1.0, 1.15, 1.0, 1.0, 1.0, 1.0, 1.0, 1.25, 1.0, 1.0]
    auto_sequence = 0
    for index, slot in enumerate(slots):
        if slot["protected"] is None:
            slot["speed"] = min(speed_pattern[auto_sequence % len(speed_pattern)], 1.15) if index == cue_slot else speed_pattern[auto_sequence % len(speed_pattern)]
            auto_sequence += 1
        else:
            slot["speed"] = 1.0

    plan: list[SegmentPlan] = []
    actual_output_cursor = 0.0
    for window_index, intervals in enumerate(auto_by_window):
        window_slots = [slot for slot in slots if slot["window"] == window_index]
        needed = sum((slot["visible"] + slot["transition"]) * slot["speed"] for slot in window_slots)
        available = sum(interval.duration for interval in intervals)
        short_gap_count = sum(
            1 for slot in window_slots[:-1]
            if slot["visible"] < song.source_progression.short_cut_threshold_seconds
        )
        fixed_skip = short_gap_count * song.source_progression.short_cut_advance_seconds
        if needed + fixed_skip > available + 0.000001:
            raise ValueError(f"Automatic footage is short by {needed + fixed_skip - available:.3f} seconds.")
        flexible_count = max(len(window_slots) - 1 - short_gap_count, 0)
        flexible_skip = max(available - needed - fixed_skip, 0.0) / max(flexible_count, 1)
        source_cursor = _IntervalCursor(intervals)

        for slot_index, slot in enumerate(window_slots):
            source_needed = (slot["visible"] + slot["transition"]) * slot["speed"]
            pieces = source_cursor.take(source_needed)
            remaining_output = slot["visible"] + slot["transition"]
            for piece_index, piece in enumerate(pieces):
                output_duration = piece.duration / slot["speed"]
                is_last_piece = piece_index == len(pieces) - 1
                transition = slot["transition"] if is_last_piece else 0.0
                visible_duration = output_duration - transition
                effect = _effect_for_time(song, slot["start"]) if piece_index == 0 else "none"
                segment_index = len(plan)
                plan.append(SegmentPlan(
                    index=segment_index,
                    source_start=piece.start,
                    source_duration=piece.duration,
                    output_duration=output_duration,
                    speed=slot["speed"],
                    style="sepia" if effect == "sepia" else "natural",
                    zoom=1.045 if segment_index % 3 != 1 else 1.0,
                    motion_blur=segment_index % 5 == 0 and slot["start"] / max(song.total_duration_seconds, 1) > 0.45,
                    cue=slots.index(slot) == cue_slot,
                    visible_start=actual_output_cursor,
                    visible_duration=visible_duration,
                    transition_after=transition,
                ))
                actual_output_cursor += visible_duration
            if slot_index < len(window_slots) - 1:
                skip = (
                    song.source_progression.short_cut_advance_seconds
                    if slot["visible"] < song.source_progression.short_cut_threshold_seconds
                    else flexible_skip
                )
                source_cursor.skip(skip)

        if window_index < len(required):
            required_start, required_end = required[window_index]
            duration = required_end - required_start
            plan.append(SegmentPlan(
                index=len(plan), source_start=required_start, source_duration=duration, output_duration=duration,
                speed=1.0, style="natural", zoom=1.0, motion_blur=False, cue=False,
                visible_start=actual_output_cursor, visible_duration=duration, transition_after=0.0, protected=True,
            ))
            actual_output_cursor += duration

    for index, segment in enumerate(plan):
        segment.index = index
    if abs(actual_output_cursor - song.total_duration_seconds) > 0.01:
        raise ValueError(
            f"Constrained montage timing differs from the song by {abs(actual_output_cursor - song.total_duration_seconds):.3f} seconds."
        )
    return plan


def build_montage_segment_plan(
    video_duration: float,
    song: SongManifest,
    excluded_ranges: list[tuple[float, float]] | None = None,
    required_ranges: list[tuple[float, float]] | None = None,
    source_boundaries: list[float] | None = None,
) -> list[SegmentPlan]:
    excluded = excluded_ranges or []
    required = required_ranges or []
    if not excluded and not required:
        return _build_legacy_montage_segment_plan(video_duration, song)
    return _build_constrained_montage_segment_plan(
        video_duration, song, excluded, required, source_boundaries or [],
    )


def build_full_length_segment_plan(
    video_duration: float,
    excluded_ranges: list[tuple[float, float]],
    source_boundaries: list[float] | None = None,
) -> list[SegmentPlan]:
    _validate_constraint_ranges(video_duration, excluded_ranges, [])
    boundaries = sorted({0.0, video_duration, *(source_boundaries or [])})
    allowed = _subtract_ranges(
        [_Interval(start, end) for start, end in zip(boundaries, boundaries[1:])],
        excluded_ranges,
    )
    if not allowed:
        raise ValueError("Excluded footage removes all usable video from the group.")
    plan: list[SegmentPlan] = []
    output_cursor = 0.0
    for index, interval in enumerate(allowed):
        plan.append(SegmentPlan(
            index=index, source_start=interval.start, source_duration=interval.duration,
            output_duration=interval.duration, speed=1.0, style="natural", zoom=1.0,
            motion_blur=False, cue=False, visible_start=output_cursor,
            visible_duration=interval.duration, transition_after=0.0,
        ))
        output_cursor += interval.duration
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
