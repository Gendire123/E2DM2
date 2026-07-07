from __future__ import annotations

import math
from dataclasses import dataclass

from .models import SegmentPlan, SongManifest


MINIMUM_CLIP_SECONDS = 0.1
MINIMUM_SHOT_FRAMES = 8
MINIMUM_INTENTIONAL_JUMP_SECONDS = 4.5
MAX_MONTAGE_CROSSFADE_SECONDS = 0.1
REQUIRED_CUT_BUFFER_SECONDS = 5.0
PLANNER_VERSION = "2.3-fragment-safe"


def canonical_fps(fps: float) -> float:
    if abs(fps - 60.0) < 0.005:
        return 60.0
    if abs(fps - 30.0) < 0.005:
        return 30.0
    if abs(fps - 59.94) < 0.05:
        return 60000 / 1001
    if abs(fps - 29.97) < 0.05:
        return 30000 / 1001
    return fps if fps > 0 else 30.0


def _frame(time_seconds: float, fps: float) -> int:
    return round(time_seconds * canonical_fps(fps))


def _seconds(frame: int, fps: float) -> float:
    return frame / canonical_fps(fps)


def _snap(time_seconds: float, fps: float) -> float:
    return _seconds(_frame(time_seconds, fps), fps)


def _required_minimum_shot_frames(song: SongManifest, fps: float) -> int:
    """Respect intentionally authored rapid cues while rejecting accidental slivers."""
    frames = [_frame(timestamp, fps) for timestamp in song.cut_timestamps]
    frames.append(_frame(song.total_duration_seconds, fps))
    authored = [end - start for start, end in zip(frames, frames[1:]) if end > start]
    return min(MINIMUM_SHOT_FRAMES, min(authored, default=MINIMUM_SHOT_FRAMES))


def _align_intervals_to_frames(intervals: list["_Interval"], fps: float) -> list["_Interval"]:
    rate = canonical_fps(fps)
    aligned = [
        _Interval(math.ceil(interval.start * rate - 0.000001) / rate, math.floor(interval.end * rate + 0.000001) / rate)
        for interval in intervals
    ]
    return [interval for interval in aligned if _frame(interval.duration, fps) >= MINIMUM_SHOT_FRAMES]


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


def _required_cut_free_ranges(
    video_duration: float,
    required_ranges: list[tuple[float, float]],
    excluded_ranges: list[tuple[float, float]],
    source_boundaries: list[float],
    song_total_duration: float | None = None,
) -> list[tuple[float, float]]:
    """Expand required footage into cut-free source ranges.

    A buffer cannot cross into another source clip or explicitly excluded footage.
    Overlapping buffers are merged so they do not introduce a cut between nearby
    required selections.
    """
    boundaries = sorted({0.0, video_duration, *(value for value in source_boundaries if 0 < value < video_duration)})
    usable = _subtract_ranges(
        [_Interval(start, end) for start, end in zip(boundaries, boundaries[1:])],
        excluded_ranges,
    )
    
    song_duration_limit = song_total_duration if song_total_duration is not None else float('inf')
    candidates = []
        
    # Only explicit REQUIRED selections become cut-free ranges. Exclusions are
    # source constraints, not mandatory footage on either side of a red mark.
    for required_start, required_end in required_ranges:
        containing = next(
            (
                interval for interval in usable
                if interval.start <= required_start + 0.000001 and interval.end >= required_end - 0.000001
            ),
            None,
        )
        if containing is None:
            raise ValueError("Required footage conflicts with excluded footage or a source clip boundary.")
        start = max(containing.start, required_start - REQUIRED_CUT_BUFFER_SECONDS)
        end = min(containing.end, required_end + REQUIRED_CUT_BUFFER_SECONDS)
        candidates.append((start, end, containing))
            
    candidates.sort(key=lambda value: value[0])
    merged = []
    for start, end, containing in candidates:
        if not merged:
            merged.append((start, end, containing))
        else:
            prev_start, prev_end, prev_containing = merged[-1]
            shares_usable = (
                containing.start <= prev_containing.start + 0.000001
                and containing.end >= prev_containing.end - 0.000001
            )
            if shares_usable and start <= prev_end + 0.000001:
                merged[-1] = (prev_start, max(prev_end, end), prev_containing)
            else:
                merged.append((start, end, containing))
    total_duration = sum(end - start for start, end, _ in merged)
    if total_duration > song_duration_limit + 0.000001:
        shortage = total_duration - song_duration_limit
        raise ValueError(f"Required footage exceeds the song by {shortage:.3f} seconds.")
    return [(start, end) for start, end, _ in merged]


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

    def take_contiguous(self, duration: float, reserve: float = 0.0) -> _Interval:
        """Take one uninterrupted source range without bridging an exclusion/clip edge."""
        while self.index < len(self.intervals):
            interval = self.intervals[self.index]
            available = interval.end - self.position
            if available + 0.000001 >= duration:
                piece = _Interval(self.position, self.position + duration)
                self.position = piece.end
                return piece
            remaining_after_discard = self.remaining - max(available, 0.0)
            if remaining_after_discard + 0.000001 < duration + reserve:
                break
            self.index += 1
            if self.index < len(self.intervals):
                self.position = self.intervals[self.index].start
        raise ValueError(f"No continuous source range can provide {duration:.3f} seconds.")

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


def _slot_treatment(song: SongManifest, start: float, duration: float, is_escalation: bool) -> dict:
    """Score an editorial treatment from musical intent instead of segment index."""
    effect = _effect_for_time(song, start)
    progress = start / max(song.total_duration_seconds, 0.001)
    score = 0.15 + min(duration / 12.0, 0.35)
    reasons = ["music-grid"]
    if progress >= 0.65:
        score += 0.15
        reasons.append("late-energy")
    if effect in {"heartbeat", "flash"}:
        score += 0.2
        reasons.append(effect)
    if is_escalation:
        score += 0.4
        reasons.append("escalation")

    # Keep every automatically selected shot at its recorded cadence. Retiming
    # 59.94 fps footage with the fps filter drops frames at uneven intervals,
    # which is visible as micro-stutter during otherwise smooth drone motion.
    desired_speed = 1.0
    zoom = 1.03 if is_escalation and duration >= 1.5 else 1.0
    return {
        "effect": effect,
        "score": min(score, 1.0),
        "reason": "+".join(reasons),
        "desired_speed": desired_speed,
        "zoom": zoom,
        "motion_blur": False,
    }


def _gap_weight(slot: dict, following: dict) -> float:
    """Prefer temporal jumps on hard musical cuts, not underneath dissolves."""
    if slot.get("continuous_boundary", False):
        return 0.0
    weight = 3.0 if slot["transition_frames"] == 0 else 0.25
    if following["treatment"]["effect"] in {"heartbeat", "flash"}:
        weight += 1.5
    if following["is_escalation"]:
        weight += 2.0
    return weight


def _allocate_scored_source(intervals: list[_Interval], slots: list[dict], fps: float) -> list[_Interval]:
    """Choose the widest feasible, deterministic source spread for a music window."""
    needs = [_seconds(slot["source_frames"], fps) for slot in slots]
    available = sum(interval.duration for interval in intervals)
    needed = sum(needs)
    if needed > available + 0.000001:
        raise ValueError(f"Automatic footage is short by {needed - available:.3f} seconds.")
    weights = [_gap_weight(slot, following) for slot, following in zip(slots, slots[1:])]
    weight_total = sum(weights)
    full_budget = max(available - needed, 0.0)
    intentional = [slot.get("intentional_jump", False) for slot in slots[:-1]]
    intentional_count = sum(intentional)
    minimum_jump = (
        min(MINIMUM_INTENTIONAL_JUMP_SECONDS, full_budget / intentional_count)
        if intentional_count else 0.0
    )
    minimum_skips = [minimum_jump if needs_jump else 0.0 for needs_jump in intentional]
    extra_budget = max(full_budget - sum(minimum_skips), 0.0)
    extra_skips = [extra_budget * weight / weight_total if weight_total else 0.0 for weight in weights]

    # Crossing an exclusion can discard the tail of a usable interval. Find
    # the highest extra-coverage scale while preserving intentional long jumps.
    for scale_step in range(100, -1, -2):
        scale = scale_step / 100
        base_skips = [minimum + extra * scale for minimum, extra in zip(minimum_skips, extra_skips)]
        cursor = _IntervalCursor(intervals)
        pieces: list[_Interval] = []
        try:
            for index, need in enumerate(needs):
                future = sum(needs[index + 1:])
                pieces.append(cursor.take_contiguous(need, future))
                if index < len(base_skips):
                    future_minimum = sum(minimum_skips[index + 1:])
                    maximum_skip = max(cursor.remaining - future - future_minimum, 0.0)
                    if maximum_skip < minimum_skips[index] - 0.5 / canonical_fps(fps):
                        raise ValueError("Fragmented footage cannot preserve an intentional source jump.")
                    requested = base_skips[index]
                    cursor.skip(_snap(min(requested, maximum_skip), fps))
            return pieces
        except ValueError:
            continue
    raise ValueError("No forward-only contiguous source allocation satisfies the montage timeline.")


def _demote_weakest_intentional_jump(slots: list[dict], minimum_shot_frames: int) -> bool:
    """Trade the weakest dissolve for continuity when fragmentation consumes its jump budget."""
    candidates = [index for index, slot in enumerate(slots[:-1]) if slot.get("intentional_jump")]
    if not candidates:
        return False
    index = min(
        candidates,
        key=lambda value: (
            slots[value + 1]["treatment"]["score"],
            slots[value]["visible_frames"],
            -value,
        ),
    )
    slot = slots[index]
    slot["intentional_jump"] = False
    slot["continuous_boundary"] = True
    _configure_slot_frames(slot, 0, minimum_shot_frames)
    return True


def _configure_slot_frames(slot: dict, transition_frames: int, minimum_shot_frames: int) -> None:
    slot["transition_frames"] = transition_frames
    slot["transition"] = _seconds(transition_frames, slot["fps"])
    output_frames = slot["visible_frames"] + transition_frames
    desired_speed = slot["treatment"]["desired_speed"]
    source_frames = max(minimum_shot_frames, round(output_frames * desired_speed))
    slot["output_frames"] = output_frames
    slot["source_frames"] = source_frames
    slot["speed"] = source_frames / output_frames


def _select_intentional_jumps(
    slots: list[dict], available: float, fps: float, minimum_shot_frames: int,
) -> None:
    """Make each long boundary either continuous or an intentional >=4.5s jump."""
    candidates = [
        index for index, slot in enumerate(slots[:-1])
        if slot["preferred_transition_frames"] > 0
    ]
    for slot in slots:
        slot["fps"] = fps
        slot["intentional_jump"] = False
        slot["continuous_boundary"] = False
        _configure_slot_frames(slot, 0, minimum_shot_frames)

    def affordable_count() -> int:
        baseline = sum(_seconds(slot["source_frames"], fps) for slot in slots)
        budget = max(available - baseline, 0.0)
        transition_cost = _seconds(
            max((slots[index]["preferred_transition_frames"] for index in candidates), default=0), fps,
        )
        return min(len(candidates), int(budget // (MINIMUM_INTENTIONAL_JUMP_SECONDS + transition_cost)))

    selected_count = affordable_count()
    if selected_count < len(candidates) and any(slot["treatment"]["desired_speed"] > 1 for slot in slots):
        # Clear optional speed effects before sacrificing purposeful edit points.
        for slot in slots:
            slot["treatment"]["desired_speed"] = 1.0
            slot["treatment"]["motion_blur"] = False
            slot["treatment"]["reason"] += "+jump-priority"
            _configure_slot_frames(slot, 0, minimum_shot_frames)
        selected_count = affordable_count()

    ranked = sorted(
        candidates,
        key=lambda index: (
            -slots[index + 1]["treatment"]["score"],
            -slots[index]["visible_frames"],
            index,
        ),
    )
    selected = set(ranked[:selected_count])
    for index in candidates:
        slot = slots[index]
        if index in selected:
            slot["intentional_jump"] = True
            _configure_slot_frames(slot, slot["preferred_transition_frames"], minimum_shot_frames)
        else:
            slot["continuous_boundary"] = True

    while selected:
        required_jump_budget = len(selected) * MINIMUM_INTENTIONAL_JUMP_SECONDS
        used = sum(_seconds(slot["source_frames"], fps) for slot in slots)
        if available - used >= required_jump_budget - 0.5 / canonical_fps(fps):
            break
        demoted = next(index for index in reversed(ranked) if index in selected)
        selected.remove(demoted)
        slots[demoted]["intentional_jump"] = False
        slots[demoted]["continuous_boundary"] = True
        _configure_slot_frames(slots[demoted], 0, minimum_shot_frames)


def _build_constrained_montage_segment_plan(
    video_duration: float,
    song: SongManifest,
    excluded_ranges: list[tuple[float, float]],
    required_ranges: list[tuple[float, float]],
    source_boundaries: list[float],
    output_fps: float,
) -> list[SegmentPlan]:
    _validate_constraint_ranges(video_duration, excluded_ranges, required_ranges)
    minimum_shot_frames = _required_minimum_shot_frames(song, output_fps)
    boundaries = sorted({0.0, video_duration, *(value for value in source_boundaries if 0 < value < video_duration)})
    base_intervals = [_Interval(start, end) for start, end in zip(boundaries, boundaries[1:])]
    usable = _align_intervals_to_frames(_subtract_ranges(base_intervals, excluded_ranges), output_fps)
    usable_duration = sum(interval.duration for interval in usable)
    frame_tolerance = 1 / canonical_fps(output_fps)
    if usable_duration < song.minimum_source_duration_seconds - frame_tolerance - 0.000001:
        shortage = song.minimum_source_duration_seconds - usable_duration
        if excluded_ranges:
            raise ValueError(f"Excluded footage leaves the group {shortage:.3f} seconds short of this song's requirement.")
        raise ValueError(f"The source footage is too short by {shortage:.3f} seconds for this song.")

    required = _required_cut_free_ranges(
        video_duration, required_ranges, excluded_ranges, source_boundaries, song.total_duration_seconds,
    )
    required = [
        (interval.start, interval.end)
        for interval in _align_intervals_to_frames(
            [_Interval(start, end) for start, end in required], output_fps,
        )
    ]
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
    timeline_frames = _frame(song.total_duration_seconds, output_fps)
    authored_frames = {_frame(timestamp, output_fps) for timestamp in song.cut_timestamps}
    authored_frames.add(_frame(song.escalation_seconds, output_fps))
    for index, (source_start, source_end) in enumerate(required):
        requested_start_frame = _frame(output_cursor + output_gaps[index], output_fps)
        duration_frames = _frame(source_end - source_start, output_fps)
        previous_end_frame = _frame(output_cursor, output_fps)

        def boundary_is_safe(frame: int) -> bool:
            distance = min((abs(frame - authored) for authored in authored_frames), default=MINIMUM_SHOT_FRAMES)
            return distance == 0 or distance >= minimum_shot_frames

        candidate_start_frame = requested_start_frame
        search_limit = max(minimum_shot_frames, round(canonical_fps(output_fps) * 2))
        for distance in range(search_limit + 1):
            candidates = (requested_start_frame + distance, requested_start_frame - distance)
            match = next((
                candidate for candidate in candidates
                if candidate >= previous_end_frame
                and candidate + duration_frames <= timeline_frames
                and boundary_is_safe(candidate)
                and boundary_is_safe(candidate + duration_frames)
            ), None)
            if match is not None:
                candidate_start_frame = match
                break
        output_cursor = _seconds(candidate_start_frame, output_fps)
        protected_end = _seconds(candidate_start_frame + duration_frames, output_fps)
        protected_output.append((output_cursor, protected_end, index))
        output_cursor = protected_end

    timeline_end = _snap(song.total_duration_seconds, output_fps)
    output_boundaries = {0.0, timeline_end}
    for timestamp in song.cut_timestamps:
        if 0 <= timestamp <= song.total_duration_seconds and not any(
            start + 0.000001 < timestamp < end - 0.000001 for start, end, _ in protected_output
        ):
            output_boundaries.add(_snap(timestamp, output_fps))
    escalation = _snap(song.escalation_seconds, output_fps)
    if minimum_shot_frames <= _frame(escalation, output_fps) <= _frame(timeline_end, output_fps) - minimum_shot_frames:
        nearest_boundary_frames = min(
            (_frame(abs(existing - escalation), output_fps) for existing in output_boundaries),
            default=minimum_shot_frames,
        )
        if nearest_boundary_frames >= minimum_shot_frames and not any(
            start + 0.000001 < escalation < end - 0.000001 for start, end, _ in protected_output
        ):
            output_boundaries.add(escalation)
    for start, end, _ in protected_output:
        output_boundaries.update((start, end))
    ordered_output = sorted(output_boundaries)

    slots: list[dict] = []
    pending_start: float | None = None
    pending_frames = 0
    for start, end in zip(ordered_output, ordered_output[1:]):
        visible_frames = _frame(end - start, output_fps)
        protected_index = next(
            (index for protected_start, protected_end, index in protected_output
             if start >= protected_start - 0.000001 and end <= protected_end + 0.000001),
            None,
        )
        window_index = (
            None if protected_index is not None else
            sum(1 for _start, protected_end, _index in protected_output if protected_end <= start + 0.000001)
        )
        if visible_frames < minimum_shot_frames:
            if (
                slots and slots[-1]["protected"] is None and protected_index is None
                and slots[-1]["window"] == window_index
            ):
                slots[-1]["visible_frames"] += visible_frames
                slots[-1]["visible"] = _seconds(slots[-1]["visible_frames"], output_fps)
            else:
                pending_start = start if pending_start is None else pending_start
                pending_frames += visible_frames
            continue
        if pending_frames and protected_index is None:
            start = pending_start if pending_start is not None else start
            visible_frames += pending_frames
            pending_start = None
            pending_frames = 0
        if protected_index is not None:
            slots.append({
                "start": start, "visible": _seconds(visible_frames, output_fps),
                "visible_frames": visible_frames, "protected": protected_index, "window": None,
            })
            continue
        slots.append({
            "start": start, "visible": _seconds(visible_frames, output_fps),
            "visible_frames": visible_frames, "protected": None, "window": window_index,
        })
    if pending_frames and slots:
        slots[-1]["visible_frames"] += pending_frames
        slots[-1]["visible"] = _seconds(slots[-1]["visible_frames"], output_fps)

    for index, slot in enumerate(slots):
        if index == len(slots) - 1 or slot["protected"] is not None:
            transition_frames = 0
        else:
            adjacent_short = (
                slot["visible"] < song.transitions.hard_cut_threshold_seconds
                or slots[index + 1]["visible"] < song.transitions.hard_cut_threshold_seconds
            )
            transition_seconds = min(song.transitions.duration_seconds, MAX_MONTAGE_CROSSFADE_SECONDS)
            transition_frames = 0 if adjacent_short else max(1, _frame(transition_seconds, output_fps))
        slot["transition_frames"] = transition_frames
        slot["transition"] = _seconds(transition_frames, output_fps)
        slot["preferred_transition_frames"] = transition_frames

    for index, slot in enumerate(slots):
        if slot["protected"] is None:
            is_escalation = abs(slot["start"] - escalation) <= 0.5 / canonical_fps(output_fps)
            treatment = _slot_treatment(song, slot["start"], slot["visible"], is_escalation)
            slot["is_escalation"] = is_escalation
            slot["treatment"] = treatment
            slot["fps"] = output_fps
            _configure_slot_frames(slot, slot["preferred_transition_frames"], minimum_shot_frames)
        else:
            slot["is_escalation"] = False
            slot["treatment"] = {
                "effect": "none", "score": 1.0, "reason": "required",
                "desired_speed": 1.0, "zoom": 1.0, "motion_blur": False,
            }
            slot["fps"] = output_fps
            _configure_slot_frames(slot, 0, minimum_shot_frames)

    plan: list[SegmentPlan] = []
    actual_output_frame = 0
    for window_index, intervals in enumerate(auto_by_window):
        window_slots = [slot for slot in slots if slot["window"] == window_index]
        available = sum(interval.duration for interval in intervals)
        _select_intentional_jumps(window_slots, available, output_fps, minimum_shot_frames)
        needed = sum(_seconds(slot["source_frames"], output_fps) for slot in window_slots)
        if needed > available + 0.000001:
            # Source sufficiency takes priority over optional speed treatments.
            for slot in window_slots:
                slot["source_frames"] = slot["output_frames"]
                slot["speed"] = 1.0
                slot["treatment"]["motion_blur"] = False
                slot["treatment"]["reason"] += "+native-cadence"
            needed = sum(_seconds(slot["source_frames"], output_fps) for slot in window_slots)
        shortage_frames = math.ceil(max(needed - available, 0.0) * canonical_fps(output_fps) - 0.000001)
        if 0 < shortage_frames <= 1 and window_slots:
            longest = max(window_slots, key=lambda slot: slot["source_frames"])
            longest["source_frames"] -= shortage_frames
            longest["speed"] = longest["source_frames"] / longest["output_frames"]
            longest["treatment"]["reason"] += "+frame-fit"
            needed = sum(_seconds(slot["source_frames"], output_fps) for slot in window_slots)
        if needed > available + 0.000001:
            raise ValueError(f"Automatic footage is short by {needed - available:.3f} seconds.")
        while True:
            try:
                allocated_pieces = _allocate_scored_source(intervals, window_slots, output_fps)
                break
            except ValueError:
                if not _demote_weakest_intentional_jump(window_slots, minimum_shot_frames):
                    raise

        for slot_index, slot in enumerate(window_slots):
            piece = allocated_pieces[slot_index]
            output_duration = _seconds(slot["output_frames"], output_fps)
            transition = _seconds(slot["transition_frames"], output_fps)
            visible_duration = _seconds(slot["visible_frames"], output_fps)
            treatment = slot["treatment"]
            segment_index = len(plan)
            plan.append(SegmentPlan(
                index=segment_index,
                source_start=piece.start,
                source_duration=piece.duration,
                output_duration=output_duration,
                speed=slot["speed"],
                style="sepia" if treatment["effect"] == "sepia" else "natural",
                zoom=treatment["zoom"],
                motion_blur=treatment["motion_blur"],
                cue=slot["is_escalation"],
                visible_start=_seconds(actual_output_frame, output_fps),
                visible_duration=visible_duration,
                transition_after=transition,
                source_start_frame=_frame(piece.start, output_fps),
                source_frame_count=slot["source_frames"],
                output_start_frame=actual_output_frame,
                output_frame_count=slot["output_frames"],
                selection_score=round(treatment["score"], 4),
                selection_reason=treatment["reason"],
            ))
            actual_output_frame += slot["visible_frames"]

        if window_index < len(required):
            required_start, required_end = required[window_index]
            duration_frames = _frame(required_end - required_start, output_fps)
            duration = _seconds(duration_frames, output_fps)
            plan.append(SegmentPlan(
                index=len(plan), source_start=required_start, source_duration=duration, output_duration=duration,
                speed=1.0, style="natural", zoom=1.0, motion_blur=False, cue=False,
                visible_start=_seconds(actual_output_frame, output_fps), visible_duration=duration,
                transition_after=0.0, protected=True,
                source_start_frame=_frame(required_start, output_fps), source_frame_count=duration_frames,
                output_start_frame=actual_output_frame, output_frame_count=duration_frames,
                selection_score=1.0, selection_reason="explicit-required",
            ))
            actual_output_frame += duration_frames

    for index, segment in enumerate(plan):
        segment.index = index
    actual_output_cursor = _seconds(actual_output_frame, output_fps)
    if abs(actual_output_cursor - timeline_end) > 0.5 / canonical_fps(output_fps):
        raise ValueError(
            f"Constrained montage timing differs from the song by {abs(actual_output_cursor - timeline_end):.3f} seconds."
        )
    return plan


def build_montage_segment_plan(
    video_duration: float,
    song: SongManifest,
    excluded_ranges: list[tuple[float, float]] | None = None,
    required_ranges: list[tuple[float, float]] | None = None,
    source_boundaries: list[float] | None = None,
    output_fps: float = 60.0,
) -> list[SegmentPlan]:
    excluded = excluded_ranges or []
    required = required_ranges or []
    return _build_constrained_montage_segment_plan(
        video_duration, song, excluded, required, source_boundaries or [], output_fps,
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


def validate_montage_plan(
    plan: list[SegmentPlan],
    song: SongManifest,
    fps: float,
    excluded_ranges: list[tuple[float, float]] | None = None,
    allow_protected_cue_gaps: bool = False,
) -> dict:
    """Return machine-readable frame, cue, exclusion, and ending QC."""
    rate = canonical_fps(fps)
    starts = {
        segment.output_start_frame
        if segment.output_start_frame is not None else round(segment.visible_start * rate)
        for segment in plan
    }
    cue_frames = [round(timestamp * rate) for timestamp in song.cut_timestamps]
    aligned_cues = sum(frame in starts for frame in cue_frames)
    escalation_frame = round(song.escalation_seconds * rate)
    required_minimum_frames = _required_minimum_shot_frames(song, fps)
    min_frames = min(
        (round(segment.visible_duration * rate) for segment in plan),
        default=0,
    )
    frame_aligned = all(
        abs(segment.visible_start * rate - round(segment.visible_start * rate)) < 0.001
        and abs(segment.source_start * rate - round(segment.source_start * rate)) < 0.001
        and abs(segment.source_duration * rate - round(segment.source_duration * rate)) < 0.001
        for segment in plan
    )
    excluded_overlaps = []
    for segment in plan:
        source_end = segment.source_start + segment.source_duration
        for start, end in excluded_ranges or []:
            if min(source_end, end) - max(segment.source_start, start) > 0.5 / rate:
                excluded_overlaps.append(segment.index)
                break
    cuts_end_frame = round(song.cuts_end_seconds * rate)
    late_starts = sorted(frame for frame in starts if frame > cuts_end_frame)
    transition_jumps = [
        current.source_start - (previous.source_start + previous.source_duration)
        for previous, current in zip(plan, plan[1:])
        if previous.transition_after > 0
    ]
    short_transition_jumps = [
        jump for jump in transition_jumps
        if jump < MINIMUM_INTENTIONAL_JUMP_SECONDS - 0.5 / rate
    ]
    long_boundary_gaps = [
        current.source_start - (previous.source_start + previous.source_duration)
        for previous, current in zip(plan, plan[1:])
        if not previous.protected and not current.protected
        and previous.visible_duration >= song.transitions.hard_cut_threshold_seconds
        and current.visible_duration >= song.transitions.hard_cut_threshold_seconds
    ]
    ambiguous_long_jumps = [
        gap for gap in long_boundary_gaps
        if 0.5 / rate < gap < MINIMUM_INTENTIONAL_JUMP_SECONDS - 0.5 / rate
    ]
    duration_frames = sum(round(segment.visible_duration * rate) for segment in plan)
    target_frames = round(song.total_duration_seconds * rate)
    errors: list[str] = []
    warnings: list[str] = []
    if min_frames < required_minimum_frames:
        errors.append(f"minimum shot is {min_frames} frames; expected at least {required_minimum_frames}")
    if not frame_aligned:
        errors.append("one or more source/output times are off the frame grid")
    if excluded_overlaps:
        errors.append(f"segments overlap excluded footage: {excluded_overlaps}")
    if aligned_cues != len(cue_frames):
        message = f"aligned {aligned_cues}/{len(cue_frames)} music cues"
        (warnings if allow_protected_cue_gaps else errors).append(message)
    if escalation_frame not in starts:
        errors.append("escalation has no frame-aligned visual event")
    if late_starts:
        errors.append(f"{len(late_starts)} shot start(s) occur after cuts_end_seconds")
    if abs(duration_frames - target_frames) > 1:
        errors.append(f"timeline differs from soundtrack by {abs(duration_frames - target_frames)} frames")
    if short_transition_jumps:
        warnings.append(
            f"{len(short_transition_jumps)} transition jump(s) are below the "
            f"{MINIMUM_INTENTIONAL_JUMP_SECONDS:.1f}s preferred target"
        )
    if ambiguous_long_jumps:
        errors.append(
            f"{len(ambiguous_long_jumps)} long cut(s) use an ambiguous source jump below "
            f"{MINIMUM_INTENTIONAL_JUMP_SECONDS:.1f}s"
        )
    return {
        "status": "pass" if not errors else "fail",
        "planner_version": PLANNER_VERSION,
        "fps": rate,
        "minimum_shot_frames": min_frames,
        "required_minimum_shot_frames": required_minimum_frames,
        "frame_aligned": frame_aligned,
        "music_cues_total": len(cue_frames),
        "music_cues_aligned": aligned_cues,
        "escalation_aligned": escalation_frame in starts,
        "excluded_overlap_count": len(excluded_overlaps),
        "late_cut_count": len(late_starts),
        "preferred_source_jump_seconds": MINIMUM_INTENTIONAL_JUMP_SECONDS,
        "minimum_transition_source_jump_seconds": (
            round(min(transition_jumps), 6) if transition_jumps else None
        ),
        "short_transition_jump_count": len(short_transition_jumps),
        "ambiguous_long_jump_count": len(ambiguous_long_jumps),
        "maximum_crossfade_seconds": round(max((segment.transition_after for segment in plan), default=0.0), 6),
        "duration_error_frames": abs(duration_frames - target_frames),
        "errors": errors,
        "warnings": warnings,
    }


def validate_forward_progression(plan: list[SegmentPlan], short_advance: float, threshold: float) -> list[str]:
    """Validate forward-only source use; gap sizes are now selected by score."""
    del short_advance, threshold
    errors: list[str] = []
    for previous, current in zip(plan, plan[1:]):
        previous_end = previous.source_start + previous.source_duration
        if current.source_start < previous_end - 0.000001:
            errors.append(f"Segments {previous.index} and {current.index} overlap.")
    return errors
