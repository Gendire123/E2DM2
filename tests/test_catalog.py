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
    song_ids = [song.song_id for song in songs]
    assert "epic-montage-1" in song_ids
    assert "epic-montage-2" in song_ids
    assert "epic-montage-3" in song_ids
    assert all(song.readonly for song in songs)
    epic_1 = next(song for song in songs if song.song_id == "epic-montage-1")
    epic_2 = next(song for song in songs if song.song_id == "epic-montage-2")
    assert filter_songs(songs, mood="heartbeat") == [epic_2]
    assert filter_songs(songs, text="montage 1") == [epic_1]
    assert epic_1 in filter_songs(songs, energy="high")
    assert epic_2 in filter_songs(songs, energy="high")


def test_epic_two_heartbeat_manifest():
    song = next(
        song for song in load_song_catalog(custom_root=Path("missing-library"))
        if song.song_id == "epic-montage-2"
    )
    assert song.heartbeat.opacity == pytest.approx(0.3)
    assert song.heartbeat.fade_seconds == pytest.approx(0.5)
    assert song.heartbeat.timestamps == []


def test_duplicate_builtin_creates_editable_manifest(tmp_path):
    original = next(song for song in load_song_catalog(custom_root=tmp_path) if song.song_id == "epic-montage-1")
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
    song = next(
        song for song in load_song_catalog(custom_root=Path("missing-library"))
        if song.song_id == "epic-montage-1"
    )
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
    
    song = next(song for song in load_song_catalog(custom_root=tmp_path) if song.song_id == "epic-montage-1")
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
    epic_1 = next(song for song in songs if song.song_id == "epic-montage-1")
    epic_2 = next(song for song in songs if song.song_id == "epic-montage-2")
    assert len(epic_1.effects) == 29
    assert epic_1.effects[18] == "slow_fade_out"
    assert epic_1.effects[19] == "flash"
    assert epic_1.effects.count("none") == 27

    assert len(epic_2.effects) == 86
    assert epic_2.effects.count("heartbeat") == 0


def test_delete_current_song(monkeypatch, tmp_path, qtbot):
    from e2dm2.catalog import load_song_catalog, duplicate_song
    from e2dm2.editor import SongEditorDialog
    from e2dm2.ui import AlphaEntitlementProvider
    from PySide6.QtWidgets import QMessageBox
    
    library_dir = tmp_path / "library"
    library_dir.mkdir()
    
    songs = load_song_catalog(custom_root=library_dir)
    original = next(song for song in songs if song.song_id == "epic-montage-1")
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
    original = next(song for song in songs if song.song_id == "epic-montage-1")
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
    monkeypatch.setattr("e2dm2.editor.save_custom_song", lambda song, audio, library_root=None: save_custom_song(song, audio, library_dir))
    monkeypatch.setattr(dialog, "reload_catalog", lambda *args, **kwargs: None)
    
    from e2dm2.catalog import save_custom_song
    dialog.save_current()
    
    # Check that new folder and manifest exist
    new_manifest = library_dir / "renamed-song" / "preset.json"
    assert new_manifest.exists()
    
    # Check that old folder is deleted
    assert not duplicate.manifest_path.exists()


def test_new_song_workflow_dialog(monkeypatch, tmp_path, qtbot):
    from e2dm2.editor import SongEditorDialog, WorkflowSelectionDialog
    from e2dm2.ui import AlphaEntitlementProvider
    from PySide6.QtWidgets import QDialog, QFileDialog
    
    dialog = SongEditorDialog(AlphaEntitlementProvider())
    qtbot.addWidget(dialog)
    
    test_audio = tmp_path / "test_track.m4a"
    test_audio.write_bytes(b"mock audio data")
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *args: (str(test_audio), "Audio"))
    
    monkeypatch.setattr(WorkflowSelectionDialog, "exec", lambda self: QDialog.DialogCode.Accepted)
    monkeypatch.setattr(WorkflowSelectionDialog, "selected_workflow", lambda self: "epic_montage")
    monkeypatch.setattr(WorkflowSelectionDialog, "is_builtin", lambda self: True)
    
    # Calculate expected index based on the initial catalog
    import re
    existing_indices = []
    for s in dialog.songs:
        match = re.match(r"^epic-montage-(\d+)$", s.song_id)
        if match:
            existing_indices.append(int(match.group(1)))
    next_idx = max(existing_indices, default=0) + 1

    dialog.new_song()
    
    assert dialog.current is not None
    assert dialog.current.workflow.value == "epic_montage"
    assert dialog.current.readonly is True
    assert dialog.current.title == f"Epic Montage {next_idx}"
    assert dialog.current.song_id == f"epic-montage-{next_idx}"
    assert dialog.current.audio_file == f"EpicMusic{next_idx}.m4a"
    assert dialog.current.artist == "E2DM2 Library"
    from e2dm2.catalog import BUILTIN_SONG_ROOT
    expected_path = BUILTIN_SONG_ROOT / f"epic-montage-{next_idx}" / f"EpicMusic{next_idx}.m4a"
    assert dialog.audio_edit.text() == str(expected_path)


def test_real_estate_song_dialog_workflow(monkeypatch, tmp_path, qtbot):
    from e2dm2.editor import SongEditorDialog, WorkflowSelectionDialog
    from e2dm2.ui import AlphaEntitlementProvider
    from e2dm2.models import WorkflowMode
    from PySide6.QtWidgets import QDialog, QFileDialog
    
    dialog = SongEditorDialog(AlphaEntitlementProvider(), workflow_filter=WorkflowMode.REAL_ESTATE)
    qtbot.addWidget(dialog)
    
    assert dialog.workflow_filter == WorkflowMode.REAL_ESTATE
    
    test_audio = tmp_path / "real_estate_music.mp3"
    test_audio.write_bytes(b"mock audio data")
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *args: (str(test_audio), "Audio"))
    
    monkeypatch.setattr(WorkflowSelectionDialog, "exec", lambda self: QDialog.DialogCode.Accepted)
    monkeypatch.setattr(WorkflowSelectionDialog, "selected_workflow", lambda self: "real_estate")
    monkeypatch.setattr(WorkflowSelectionDialog, "is_builtin", lambda self: False)
    
    import re
    existing_indices = []
    for s in dialog.songs:
        match = re.match(r"^real-estate-(\d+)$", s.song_id)
        if match:
            existing_indices.append(int(match.group(1)))
    next_idx = max(existing_indices, default=0) + 1

    dialog.new_song()
    
    assert dialog.current is not None
    assert dialog.current.workflow == WorkflowMode.REAL_ESTATE
    assert dialog.current.readonly is False
    assert dialog.current.title == f"Real Estate {next_idx}"
    assert dialog.current.song_id == f"real-estate-{next_idx}"
    assert dialog.current.audio_file == f"RealEstate{next_idx}.mp3"
    assert dialog.current.artist == "E2DM2 Library"


def test_filtered_library_locks_new_song_to_full_length(monkeypatch, tmp_path, qtbot):
    from e2dm2.editor import SongEditorDialog, WorkflowSelectionDialog
    from e2dm2.ui import AlphaEntitlementProvider
    from e2dm2.models import WorkflowMode
    from PySide6.QtWidgets import QDialog, QFileDialog

    monkeypatch.setattr(
        "e2dm2.editor.load_song_catalog",
        lambda: load_song_catalog(custom_root=tmp_path / "missing-library"),
    )
    dialog = SongEditorDialog(AlphaEntitlementProvider(), workflow_filter=WorkflowMode.FULL_LENGTH)
    qtbot.addWidget(dialog)
    assert dialog.song_list.count() == 4
    assert [song.song_id for song in dialog.filtered_songs] == [
        "drone-music-1", "drone-music-2", "drone-music-3", "drone-music-4",
    ]
    assert all(dialog.song_list.item(row).text().endswith("  [built-in]") for row in range(4))
    assert dialog.current.song_id == "drone-music-1"
    assert dialog.audio_edit.text().endswith("e2dm2\\assets\\songs\\drone-music-1\\dronemusic1.m4a")
    assert dialog.save_button.isEnabled()
    assert dialog.title_edit.isEnabled()
    assert dialog.artist_edit.isEnabled()
    assert dialog.id_edit.isEnabled()
    assert dialog.moods_edit.isEnabled()
    assert dialog.energy_combo.isEnabled()
    assert dialog.bpm_spin.isEnabled()
    assert dialog.audio_edit.isEnabled()
    assert dialog.audio_button.isEnabled()
    assert dialog.total_spin.isEnabled()
    assert dialog.minimum_source_spin.isEnabled()
    assert dialog.opening_spin.isEnabled()
    assert dialog.cuts_end_spin.isEnabled()
    assert dialog.fade_out_spin.isEnabled()
    assert dialog.escalation_spin.isEnabled()
    assert dialog.transition_spin.isEnabled()
    assert dialog.hard_cut_spin.isEnabled()
    assert dialog.short_threshold_spin.isEnabled()
    assert dialog.short_advance_spin.isEnabled()
    assert not dialog.delete_button.isEnabled()
    monkeypatch.setattr(dialog, "load_waveform", lambda *_args: None)
    test_audio = tmp_path / "full_length_music.mp3"
    test_audio.write_bytes(b"mock audio data")
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *args: (str(test_audio), "Audio"))

    def accept_locked_workflow(workflow_dialog):
        assert workflow_dialog.combo.currentData() == WorkflowMode.FULL_LENGTH.value
        assert not workflow_dialog.combo.isEnabled()
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(WorkflowSelectionDialog, "exec", accept_locked_workflow)
    dialog.new_song()

    assert dialog.current is not None
    assert dialog.current.workflow is WorkflowMode.FULL_LENGTH
