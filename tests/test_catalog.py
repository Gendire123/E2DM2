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
    assert song.heartbeat.opacity == pytest.approx(0.3)
    assert song.heartbeat.fade_seconds == pytest.approx(0.5)
    assert song.heartbeat.timestamps == []


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


def test_song_manifest_effects_flow():
    from e2dm2.models import SongManifest, EnergyLevel
    from e2dm2.catalog import validate_song_manifest
    
    song = SongManifest(
        schema_version=1, song_id="test-song", title="Test Song", artist="Artist",
        audio_file="audio.m4a", moods=["epic"], bpm=120.0, energy=EnergyLevel.HIGH,
        total_duration_seconds=10.0, minimum_source_duration_seconds=10.0,
        opening_fade_seconds=0.0, cuts_end_seconds=10.0, fade_out_seconds=0.0,
        escalation_seconds=0.0, cut_timestamps=[0.0, 5.0], effects=["none"]
    )
    errors = validate_song_manifest(song, require_audio=False)
    assert any("number of effects must match" in error for error in errors)
    
    songs = load_song_catalog(custom_root=Path("missing-library"))
    assert len(songs[0].effects) == 29
    assert songs[0].effects[18] == "slow_fade_out"
    assert songs[0].effects[19] == "flash"
    assert songs[0].effects.count("none") == 27
    
    assert len(songs[1].effects) == 86
    assert songs[1].effects.count("heartbeat") == 0


def test_delete_current_song(monkeypatch, tmp_path, qtbot):
    from e2dm2.catalog import load_song_catalog, duplicate_song
    from e2dm2.editor import SongEditorDialog
    from e2dm2.ui import AlphaEntitlementProvider
    from PySide6.QtWidgets import QMessageBox
    
    library_dir = tmp_path / "library"
    library_dir.mkdir()
    
    songs = load_song_catalog(custom_root=library_dir)
    original = songs[0]
    duplicate = duplicate_song(original, "dup-song", "Duplicate Title", library_root=library_dir)
    
    dialog = SongEditorDialog(AlphaEntitlementProvider())
    qtbot.addWidget(dialog)
    dialog.songs = load_song_catalog(custom_root=library_dir)
    dialog._load_selected(len(dialog.songs) - 1)
    
    assert dialog.current.song_id == "dup-song"
    assert dialog.current.manifest_path.exists()
    
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(dialog, "reload_catalog", lambda *args, **kwargs: None)
    
    dialog.delete_current()
    
    assert not duplicate.manifest_path.exists()


def test_rename_song_id(monkeypatch, tmp_path, qtbot):
    from e2dm2.catalog import load_song_catalog, duplicate_song
    from e2dm2.editor import SongEditorDialog
    from e2dm2.ui import AlphaEntitlementProvider
    
    library_dir = tmp_path / "library"
    library_dir.mkdir()
    
    songs = load_song_catalog(custom_root=library_dir)
    original = songs[0]
    duplicate = duplicate_song(original, "dup-song", "Duplicate Title", library_root=library_dir)
    
    dialog = SongEditorDialog(AlphaEntitlementProvider())
    qtbot.addWidget(dialog)
    dialog.songs = load_song_catalog(custom_root=library_dir)
    dialog._load_selected(len(dialog.songs) - 1)
    
    assert dialog.current.song_id == "dup-song"
    assert dialog.current.manifest_path.exists()
    
    # Change the song ID in the editor
    dialog.id_edit.setText("renamed-song")
    
    # Mock save_custom_song or reload_catalog library root so it saves to the temp folder
    monkeypatch.setattr("e2dm2.editor.save_custom_song", lambda song, audio, lib_root=library_dir: save_custom_song(song, audio, library_dir))
    monkeypatch.setattr(dialog, "reload_catalog", lambda *args, **kwargs: None)
    
    from e2dm2.catalog import save_custom_song
    dialog.save_current()
    
    # Check that new folder and manifest exist
    new_manifest = library_dir / "renamed-song" / "preset.json"
    assert new_manifest.exists()
    
    # Check that old folder is deleted
    assert not duplicate.manifest_path.exists()



