import json
from pathlib import Path

import pytest

from e2dm2.catalog import load_song_catalog, load_song_manifest
from e2dm2.models import EnergyLevel, ExportSize, RenderOutputPlan, SongManifest, WorkflowMode
from e2dm2.montage import (
    MINIMUM_SHOT_FRAMES,
    build_full_length_segment_plan,
    build_montage_segment_plan,
    validate_montage_plan,
)
from e2dm2.render import _montage_filter


@pytest.mark.parametrize("song_id", ["epic-montage-1", "epic-montage-2", "epic-montage-3"])
def test_builtin_plans_are_frame_aligned_and_move_forward(song_id):
    songs = load_song_catalog(custom_root=Path("missing-library"))
    song = next(s for s in songs if s.song_id == song_id)
    plan = build_montage_segment_plan(song.minimum_source_duration_seconds, song)
    qc = validate_montage_plan(plan, song, 60)
    assert qc["status"] == "pass"
    assert qc["frame_aligned"]
    assert qc["minimum_shot_frames"] >= MINIMUM_SHOT_FRAMES
    for previous, current in zip(plan, plan[1:]):
        previous_end = previous.source_start + previous.source_duration
        assert current.source_start >= previous_end


def test_builtin_plan_durations_and_cut_counts():
    songs = load_song_catalog(custom_root=Path("missing-library"))
    first = next(s for s in songs if s.song_id == "epic-montage-1")
    second = next(s for s in songs if s.song_id == "epic-montage-2")
    third = next(s for s in songs if s.song_id == "epic-montage-3")
    assert (first.total_duration_seconds, len(first.cut_timestamps)) == (150, 29)
    assert (second.total_duration_seconds, len(second.cut_timestamps)) == (227, 88)
    assert (third.total_duration_seconds, len(third.cut_timestamps)) == (239.978, 32)


def test_epic_two_filter_contains_all_heartbeat_effects():
    songs = load_song_catalog(custom_root=Path("missing-library"))
    song = next(s for s in songs if s.song_id == "epic-montage-2")
    song.effects = ["none"] * len(song.cut_timestamps)
    for i in range(15):
        song.effects[i] = "heartbeat"
    song.heartbeat.opacity = 0.2
    song.heartbeat.fade_seconds = 0.45
    segments = build_montage_segment_plan(318, song)
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
    for seg in protected:
        assert seg.style == "natural"
        assert seg.zoom == 1
        assert not seg.motion_blur
    assert not any(
        not segment.protected and segment.source_start < 65 and segment.source_start + segment.source_duration > 45
        for segment in plan
    )
    protected_end = protected[0].visible_start + protected[0].visible_duration
    assert not any(
        protected[0].visible_start < segment.visible_start < protected_end
        for segment in plan if segment is not protected[0]
    )


def test_epic_two_exclusions_keep_all_cues_and_do_not_inject_boundary_shots():
    song = next(s for s in load_song_catalog(custom_root=Path("missing-library")) if s.song_id == "epic-montage-2")
    excluded = [
        (0, 4.887), (149.556, 193.543), (269.462, 285.102),
        (351.897, 393.929), (428.141, 471.803),
        (524.262, 541.531), (587.798, 606.045),
    ]
    fps = 60000 / 1001
    plan = build_montage_segment_plan(606.045083, song, excluded_ranges=excluded, output_fps=fps)
    qc = validate_montage_plan(plan, song, fps, excluded)
    assert qc["status"] == "pass"
    assert qc["music_cues_aligned"] == qc["music_cues_total"] == 88
    assert qc["escalation_aligned"]
    assert qc["late_cut_count"] == 0
    assert qc["minimum_shot_frames"] >= MINIMUM_SHOT_FRAMES
    assert not any(segment.protected for segment in plan)
    assert all(segment.visible_start <= song.cuts_end_seconds for segment in plan)
    assert plan[-1].visible_start < song.cuts_end_seconds
    assert plan[-1].visible_start + plan[-1].visible_duration == pytest.approx(sum(s.visible_duration for s in plan))


def test_scored_treatments_replace_periodic_effect_patterns():
    song = next(s for s in load_song_catalog(custom_root=Path("missing-library")) if s.song_id == "epic-montage-2")
    plan = build_montage_segment_plan(500, song, output_fps=60)
    transformed = [segment for segment in plan if segment.speed > 1.001]
    assert transformed
    assert all(segment.visible_duration >= 3 or segment.cue for segment in transformed)
    assert [segment.index for segment in plan if segment.zoom > 1] == [
        segment.index for segment in plan if segment.cue
    ]
    assert all(segment.motion_blur == segment.cue for segment in plan)
    assert all(segment.selection_score > 0 and segment.selection_reason for segment in plan)


@pytest.mark.parametrize(
    "song_id",
    [
        "epic-montage-1", "epic-montage-2", "epic-montage-3", "epic-montage-4", "epic-montage-5",
        "real-estate-1", "real-estate-2", "real-estate-3", "real-estate-4", "real-estate-5",
    ],
)
def test_all_builtin_montages_avoid_ambiguous_long_source_jumps(song_id):
    song = next(s for s in load_song_catalog(custom_root=Path("missing-library")) if s.song_id == song_id)
    for source_duration in (
        song.minimum_source_duration_seconds,
        max(song.minimum_source_duration_seconds, song.total_duration_seconds + len(song.cut_timestamps) * 5 + 30),
    ):
        plan = build_montage_segment_plan(source_duration, song, output_fps=60)
        qc = validate_montage_plan(plan, song, 60)
        assert qc["status"] == "pass"
        assert qc["ambiguous_long_jump_count"] == 0
        assert qc["short_transition_jump_count"] == 0
        assert qc["maximum_crossfade_seconds"] <= 0.101


def test_imported_custom_song_uses_shared_intentional_jump_policy(tmp_path):
    song = SongManifest(
        schema_version=1, song_id="custom-intentional-cuts", title="Custom Intentional Cuts",
        artist="User", audio_file="audio.m4a", moods=["cinematic"], bpm=None,
        energy=EnergyLevel.HIGH, total_duration_seconds=24,
        minimum_source_duration_seconds=24, opening_fade_seconds=0,
        cuts_end_seconds=24, fade_out_seconds=0, escalation_seconds=12,
        cut_timestamps=[0, 6, 12, 18], effects=["none"] * 4,
        workflow=WorkflowMode.EPIC_MONTAGE,
    )
    folder = tmp_path / song.song_id
    folder.mkdir()
    (folder / song.audio_file).write_bytes(b"placeholder")
    (folder / "preset.json").write_text(json.dumps(song.to_dict()), encoding="utf-8")
    imported = load_song_manifest(folder / "preset.json")
    assert not imported.readonly

    tight = build_montage_segment_plan(24, imported, output_fps=60)
    tight_qc = validate_montage_plan(tight, imported, 60)
    assert tight_qc["status"] == "pass"
    assert tight_qc["ambiguous_long_jump_count"] == 0
    assert not any(segment.transition_after for segment in tight)

    ample = build_montage_segment_plan(60, imported, output_fps=60)
    ample_qc = validate_montage_plan(ample, imported, 60)
    assert ample_qc["status"] == "pass"
    assert ample_qc["minimum_transition_source_jump_seconds"] >= 4.5
    assert ample_qc["short_transition_jump_count"] == 0
    assert ample_qc["maximum_crossfade_seconds"] <= 0.101


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
