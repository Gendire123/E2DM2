from pathlib import Path

import pytest

from e2dm2.catalog import load_song_catalog
from e2dm2.models import ExportSize, RenderOutputPlan
from e2dm2.montage import build_montage_segment_plan, validate_forward_progression
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
    song = load_song_catalog(custom_root=Path("missing-library"))[1]
    with pytest.raises(ValueError, match="too short"):
        build_montage_segment_plan(200, song)

