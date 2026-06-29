from pathlib import Path

import pytest

from e2dm2.catalog import load_song_catalog
from e2dm2.models import ExportSize, RenderOutputPlan
from e2dm2.montage import build_full_length_segment_plan, build_montage_segment_plan, validate_forward_progression
from e2dm2.render import _montage_filter


@pytest.mark.parametrize("song_id", ["epic-montage-1", "epic-montage-2", "epic-montage-3"])
def test_builtin_plans_always_move_forward(song_id):
    songs = load_song_catalog(custom_root=Path("missing-library"))
    song = next(s for s in songs if s.song_id == song_id)
    plan = build_montage_segment_plan(song.minimum_source_duration_seconds, song)
    assert validate_forward_progression(
        plan,
        song.source_progression.short_cut_advance_seconds,
        song.source_progression.short_cut_threshold_seconds,
    ) == []
    for previous, current in zip(plan, plan[1:]):
        previous_end = previous.source_start + previous.source_duration
        assert current.source_start >= previous_end
        if previous.visible_duration < 5:
            assert current.source_start - previous_end == pytest.approx(1, abs=0.001)


def test_builtin_plan_durations_and_cut_counts():
    songs = load_song_catalog(custom_root=Path("missing-library"))
    first = next(s for s in songs if s.song_id == "epic-montage-1")
    second = next(s for s in songs if s.song_id == "epic-montage-2")
    third = next(s for s in songs if s.song_id == "epic-montage-3")
    assert (first.total_duration_seconds, len(first.cut_timestamps)) == (150, 29)
    assert (second.total_duration_seconds, len(second.cut_timestamps)) == (227, 86)
    assert (third.total_duration_seconds, len(third.cut_timestamps)) == (239.978, 32)


def test_epic_two_filter_contains_all_heartbeat_effects():
    songs = load_song_catalog(custom_root=Path("missing-library"))
    song = next(s for s in songs if s.song_id == "epic-montage-2")
    song.effects = ["none"] * len(song.cut_timestamps)
    for i in range(15):
        song.effects[i] = "heartbeat"
    song.heartbeat.opacity = 0.2
    song.heartbeat.fade_seconds = 0.45
    segments = build_montage_segment_plan(315, song)
    output = RenderOutputPlan(
        "test", "2720x1530_59.94fps", [], 1920, 1080, 59.94, 227,
        ExportSize.HD_1080, "test.mp4", 12000, segments,
    )
    script = _montage_filter(output, song)
    assert script.count("overlay=shortest=1") == 15
    assert "black@0.200" in script
    for timestamp in song.cut_timestamps[:15]:
        assert f"st={timestamp:.6f}:d=0.450" in script
    assert "scale=1920:1080" in script


def test_too_little_source_is_rejected():
    song = next(
        song for song in load_song_catalog(custom_root=Path("missing-library"))
        if song.song_id == "epic-montage-2"
    )
    with pytest.raises(ValueError, match="too short"):
        build_montage_segment_plan(200, song)


def test_constrained_plan_excludes_red_and_preserves_green_once():
    songs = load_song_catalog(custom_root=Path("missing-library"))
    song = next(s for s in songs if s.song_id == "epic-montage-1")
    plan = build_montage_segment_plan(
        220, song, excluded_ranges=[(20, 30)], required_ranges=[(50, 60)], source_boundaries=[110],
    )
    assert sum(segment.visible_duration for segment in plan) == pytest.approx(song.total_duration_seconds)
    assert not any(
        segment.source_start < 30 and segment.source_start + segment.source_duration > 20
        for segment in plan
    )
    protected = [segment for segment in plan if segment.protected]
    assert len(protected) == 1
    assert (protected[0].source_start, protected[0].source_duration, protected[0].speed) == (45, 20, 1)
    assert protected[0].style == "natural"
    assert protected[0].zoom == 1
    assert not protected[0].motion_blur
    assert not any(
        not segment.protected and segment.source_start < 65 and segment.source_start + segment.source_duration > 45
        for segment in plan
    )
    protected_end = protected[0].visible_start + protected[0].visible_duration
    assert not any(
        protected[0].visible_start < segment.visible_start < protected_end
        for segment in plan if segment is not protected[0]
    )


def test_multiple_required_ranges_stay_in_source_order():
    song = next(s for s in load_song_catalog(custom_root=Path("missing-library")) if s.song_id == "epic-montage-1")
    plan = build_montage_segment_plan(240, song, required_ranges=[(40, 45), (150, 158)])
    protected = [segment for segment in plan if segment.protected]
    assert [segment.source_start for segment in protected] == [35, 145]
    assert [segment.visible_start for segment in protected] == sorted(segment.visible_start for segment in protected)


def test_required_cut_buffer_clamps_to_clip_boundaries():
    song = next(s for s in load_song_catalog(custom_root=Path("missing-library")) if s.song_id == "epic-montage-1")
    plan = build_montage_segment_plan(220, song, required_ranges=[(112, 116)], source_boundaries=[110])
    protected = [segment for segment in plan if segment.protected]
    assert [(segment.source_start, segment.source_duration) for segment in protected] == [(110, 11)]


def test_overlapping_required_cut_buffers_form_one_uncut_segment():
    song = next(s for s in load_song_catalog(custom_root=Path("missing-library")) if s.song_id == "epic-montage-1")
    plan = build_montage_segment_plan(220, song, required_ranges=[(50, 53), (58, 61)])
    protected = [segment for segment in plan if segment.protected]
    assert [(segment.source_start, segment.source_duration) for segment in protected] == [(45, 21)]


def test_required_cut_buffers_do_not_merge_across_source_clips():
    song = next(s for s in load_song_catalog(custom_root=Path("missing-library")) if s.song_id == "epic-montage-1")
    plan = build_montage_segment_plan(
        220, song, required_ranges=[(105, 108), (112, 115)], source_boundaries=[110],
    )
    protected = [segment for segment in plan if segment.protected]
    assert [(segment.source_start, segment.source_duration) for segment in protected] == [(100, 10), (110, 10)]


def test_infeasible_required_and_excluded_constraints_are_rejected():
    song = next(s for s in load_song_catalog(custom_root=Path("missing-library")) if s.song_id == "epic-montage-1")
    with pytest.raises(ValueError, match="exceeds the song"):
        build_montage_segment_plan(220, song, required_ranges=[(0, 160)])
    with pytest.raises(ValueError, match="short"):
        build_montage_segment_plan(220, song, excluded_ranges=[(0, 50)])


def test_full_length_plan_removes_exclusions_and_respects_clip_boundaries():
    plan = build_full_length_segment_plan(10, [(2, 4), (7, 8)], [5])
    assert [(segment.source_start, segment.source_duration) for segment in plan] == [
        (0, 2), (4, 1), (5, 2), (8, 2),
    ]
    assert sum(segment.visible_duration for segment in plan) == 7


def test_music_effects_are_suppressed_inside_protected_output():
    song = next(s for s in load_song_catalog(custom_root=Path("missing-library")) if s.song_id == "epic-montage-1")
    segments = build_montage_segment_plan(220, song, required_ranges=[(50, 60)])
    protected = next(segment for segment in segments if segment.protected)
    protected_end = protected.visible_start + protected.visible_duration
    effect_index = next(
        index for index, timestamp in enumerate(song.cut_timestamps)
        if protected.visible_start < timestamp < protected_end
    )
    song.effects = ["none"] * len(song.cut_timestamps)
    song.effects[effect_index] = "heartbeat"
    output = RenderOutputPlan(
        "protected", "2720x1530_59.94fps", [], 1920, 1080, 59.94, song.total_duration_seconds,
        ExportSize.HD_1080, "test.mp4", 12000, segments,
    )
    script = _montage_filter(output, song)
    assert f"st={song.cut_timestamps[effect_index]:.6f}" not in script
