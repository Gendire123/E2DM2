import json
from pathlib import Path

import pytest

from e2dm2.catalog import (
    duplicate_song,
    filter_songs,
    load_song_catalog,
    load_song_manifest,
    validate_song_manifest,
)
from e2dm2.entitlements import AlphaEntitlementProvider, PRESET_EDITOR_FEATURE


def test_builtin_catalog_and_filters():
    songs = load_song_catalog(custom_root=Path("missing-library"))
    assert [song.song_id for song in songs] == ["epic-montage-1", "epic-montage-2"]
    assert all(song.readonly for song in songs)
    assert filter_songs(songs, mood="heartbeat") == [songs[1]]
    assert filter_songs(songs, text="montage 1") == [songs[0]]
    assert filter_songs(songs, energy="high") == songs


def test_epic_two_heartbeat_manifest():
    song = load_song_catalog(custom_root=Path("missing-library"))[1]
    assert song.heartbeat.opacity == pytest.approx(0.2)
    assert song.heartbeat.fade_seconds == pytest.approx(0.45)
    assert song.heartbeat.timestamps == pytest.approx([
        76.938660, 77.500484, 79.144339, 79.716567, 81.308401,
        81.870225, 83.482868, 84.065500, 215.532289, 216.094113,
        217.696352, 218.258176, 219.902031, 220.463855, 222.086901,
    ])


def test_duplicate_builtin_creates_editable_manifest(tmp_path):
    original = load_song_catalog(custom_root=tmp_path)[0]
    duplicate = duplicate_song(original, "my-epic-song", "My Epic Song", tmp_path)
    assert duplicate.readonly
    assert duplicate.audio_path.is_file()
    loaded = load_song_manifest(tmp_path / "my-epic-song" / "preset.json")
    assert loaded.song_id == "my-epic-song"
    assert loaded.cut_timestamps == original.cut_timestamps


def test_malformed_manifest_is_rejected(tmp_path):
    path = tmp_path / "preset.json"
    path.write_text(json.dumps({"schema_version": 1, "song_id": "broken"}), encoding="utf-8")
    with pytest.raises(ValueError, match="Could not load"):
        load_song_manifest(path)


def test_manifest_validation_rejects_timing_errors():
    song = load_song_catalog(custom_root=Path("missing-library"))[0]
    song.cut_timestamps = [1, 0, 1]
    errors = validate_song_manifest(song)
    assert any("begin at 0" in error for error in errors)
    assert any("sorted" in error for error in errors)
    assert any("unique" in error for error in errors)


def test_alpha_entitlement_unlocks_only_editor():
    entitlement = AlphaEntitlementProvider()
    assert entitlement.has_feature(PRESET_EDITOR_FEATURE)
    assert not entitlement.has_feature("future_feature")


def test_save_builtin_song_is_allowed(tmp_path):
    import shutil
    from e2dm2.catalog import save_custom_song
    
    song = load_song_catalog(custom_root=tmp_path)[0]
    temp_manifest_dir = tmp_path / "fake-builtin"
    temp_manifest_dir.mkdir()
    temp_manifest = temp_manifest_dir / "preset.json"
    
    shutil.copy2(song.manifest_path, temp_manifest)
    shutil.copy2(song.audio_path, temp_manifest_dir / song.audio_path.name)
    
    loaded_builtin = load_song_manifest(temp_manifest, readonly=True)
    assert loaded_builtin.readonly
    
    loaded_builtin.title = "Updated Builtin Title"
    saved = save_custom_song(loaded_builtin, loaded_builtin.audio_path, tmp_path)
    
    assert saved.readonly
    assert saved.title == "Updated Builtin Title"
    
    reloaded = load_song_manifest(temp_manifest, readonly=True)
    assert reloaded.title == "Updated Builtin Title"


