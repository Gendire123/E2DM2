import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QAbstractAnimation, QObject, QPoint, QSettings, QSize, Qt, Signal, Slot
from PySide6.QtWidgets import QMessageBox, QTableWidgetItem

from e2dm2.models import ClipSelection, MediaItem, RenderResult, SelectionType, WorkflowMode
from e2dm2.preview import ClipPreviewDialog, SelectionTimeline, format_timecode, parse_timecode
from e2dm2.editor import SongEditorDialog
from e2dm2.entitlements import AlphaEntitlementProvider
from e2dm2.ui import ClickSeekSlider, HomePage, MainWindow, OptionsDialog, SongPreviewCell, splash_screen_enabled
from e2dm2.project import create_project
from e2dm2.ui import WorkspacePage


def test_main_window_smoke(qtbot):
    window = MainWindow()
    qtbot.addWidget(window)
    assert window.size().width() == 820
    assert window.size().height() == 660
    window.show()
    assert window.windowTitle().startswith("Easy Epic Drone Movie Maker")
    assert not window.windowIcon().isNull()
    assert window.workspace.song_table.rowCount() >= 2
    assert window.home.recent_list is not None
    assert window.home.logo_label.pixmap() is not None
    assert not window.home.logo_label.pixmap().isNull()
    assert window.home.logo_label.size() == QSize(300, 200)
    assert window.home.title_label.wordWrap()
    assert not window.home.delete_button.isEnabled()
    assert window.log_dock.windowTitle() == "Backend Log"
    assert not window.log_dock.isVisible()
    assert window.options_action.text() == "Options..."
    window.center_on_active_screen()
    screen_center = window.screen().availableGeometry().center()
    frame_center = window.frameGeometry().center()
    assert abs(frame_center.x() - screen_center.x()) <= 2
    assert abs(frame_center.y() - screen_center.y()) <= 2


def test_options_dialog_persists_splash_screen_preference(qtbot, tmp_path):
    settings = QSettings(str(tmp_path / "options.ini"), QSettings.Format.IniFormat)
    dialog = OptionsDialog(settings=settings)
    qtbot.addWidget(dialog)

    assert dialog.splash_checkbox.isChecked()
    assert splash_screen_enabled(settings)

    dialog.splash_checkbox.setChecked(False)

    assert not splash_screen_enabled(settings)

    # Test output directory settings loading/saving
    assert dialog.output_edit.text() == ""
    assert settings.value("custom_output_folder", "") == ""

    # Clear/reset
    dialog._clear_output_folder()
    assert dialog.output_edit.text() == ""
    assert settings.value("custom_output_folder", "") == ""


def test_background_import_worker_is_retained(qtbot, tmp_path):
    source = tmp_path / "worker-test.mp4"
    subprocess.run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
        "-i", "color=c=blue:s=320x180:r=30:d=0.2", "-c:v", "libx264", str(source),
    ], check=True)
    page = WorkspacePage()
    qtbot.addWidget(page)
    page.set_project(create_project("Worker Test", tmp_path / "projects"))
    page.start_import([source])
    qtbot.waitUntil(lambda: page.thread is None, timeout=5000)
    assert len(page.project.settings.media) == 1
    assert page.status_label.text() == "Imported 1 clip(s)"


def test_home_page_deletes_selected_project_after_confirmation(qtbot, tmp_path, monkeypatch):
    page = HomePage()
    qtbot.addWidget(page)
    project_path = tmp_path / "project"
    project_path.mkdir()
    (project_path / "project.json").write_text("{}", encoding="utf-8")
    page.recent_list.setRowCount(1)
    item = QTableWidgetItem(project_path.name)
    page.recent_list.setItem(0, 0, item)
    item.setData(Qt.ItemDataRole.UserRole, str(project_path))
    page.recent_list.setCurrentCell(0, 0)
    assert page.delete_button.isEnabled()

    deleted = []
    monkeypatch.setattr("e2dm2.ui.QMessageBox.warning", lambda *_args, **_kwargs: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr("e2dm2.ui.delete_project", lambda path: deleted.append(path))
    page.delete_selected_project()
    assert deleted == [project_path]


def test_home_page_shows_recent_project_metadata(qtbot, tmp_path, monkeypatch):
    project = create_project("Coastal Showcase", tmp_path / "projects")
    data = json.loads((project.path / "project.json").read_text(encoding="utf-8"))
    data["created_at"] = "2026-06-20T14:30:00"
    data["updated_at"] = "2026-06-28T09:45:00"
    (project.path / "project.json").write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr("e2dm2.ui.recent_projects", lambda: [project.path])

    page = HomePage()
    qtbot.addWidget(page)
    page.refresh()

    assert page.recent_list.horizontalHeaderItem(0).text() == "Project title"
    assert page.recent_list.horizontalHeaderItem(1).text() == "Created"
    assert page.recent_list.horizontalHeaderItem(2).text() == "Last modified"
    assert page.recent_list.item(0, 0).text() == "Coastal Showcase"
    assert page.recent_list.item(0, 1).text() == "2026-06-20  14:30"
    assert page.recent_list.item(0, 2).text() == "2026-06-28  09:45"
    assert page.recent_list.item(0, 2).data(Qt.ItemDataRole.UserRole) == str(project.path)


def test_open_project_uses_latest_modified_or_selected_project(qtbot, tmp_path, monkeypatch):
    older = create_project("Older", tmp_path / "projects")
    newer = create_project("Newer", tmp_path / "projects")
    for project, updated_at in ((older, "2026-06-27T10:00:00"), (newer, "2026-06-28T10:00:00")):
        project_file = project.path / "project.json"
        data = json.loads(project_file.read_text(encoding="utf-8"))
        data["updated_at"] = updated_at
        project_file.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr("e2dm2.ui.recent_projects", lambda: [older.path, newer.path])

    page = HomePage()
    qtbot.addWidget(page)
    page.refresh()
    opened = []
    page.recent_requested.connect(opened.append)

    page.open_button.click()
    assert opened == [str(newer.path)]

    older_row = next(
        row for row in range(page.recent_list.rowCount())
        if page.recent_list.item(row, 0).data(Qt.ItemDataRole.UserRole) == str(older.path)
    )
    page.recent_list.selectRow(older_row)
    page.open_button.click()
    assert opened == [str(newer.path), str(older.path)]


def test_recent_projects_default_to_latest_and_support_column_sorting(qtbot, tmp_path, monkeypatch):
    projects = [
        create_project("zebra", tmp_path / "projects"),
        create_project("Alpha", tmp_path / "projects"),
        create_project("middle", tmp_path / "projects"),
    ]
    timestamps = ["2026-06-29T10:00:00", "2026-06-27T10:00:00", "2026-06-28T10:00:00"]
    for project, updated_at in zip(projects, timestamps):
        project_file = project.path / "project.json"
        data = json.loads(project_file.read_text(encoding="utf-8"))
        data["updated_at"] = updated_at
        project_file.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr("e2dm2.ui.recent_projects", lambda: [projects[0].path, projects[1].path, projects[2].path])

    page = HomePage()
    qtbot.addWidget(page)
    page.refresh()

    assert page.recent_list.isSortingEnabled()
    assert page.recent_list.horizontalHeader().sortIndicatorSection() == 2
    assert page.recent_list.horizontalHeader().sortIndicatorOrder() == Qt.SortOrder.DescendingOrder
    assert [page.recent_list.item(row, 0).text() for row in range(3)] == ["zebra", "middle", "Alpha"]

    page.recent_list.sortItems(0, Qt.SortOrder.AscendingOrder)
    assert [page.recent_list.item(row, 0).text() for row in range(3)] == ["Alpha", "middle", "zebra"]
    page.recent_list.sortItems(0, Qt.SortOrder.DescendingOrder)
    assert [page.recent_list.item(row, 0).text() for row in range(3)] == ["zebra", "middle", "Alpha"]


def test_produce_coerces_qt_combo_data_to_workflow_enum(qtbot, tmp_path, monkeypatch):
    class FakeRenderWorker(QObject):
        progress = Signal(object)
        finished = Signal(object)
        failed = Signal(str)

        def __init__(self, project, request, cancellation):
            super().__init__()

        @Slot()
        def run(self):
            self.finished.emit(RenderResult([]))

    monkeypatch.setattr("e2dm2.ui.RenderWorker", FakeRenderWorker)
    page = WorkspacePage()
    qtbot.addWidget(page)
    page.set_project(create_project("Produce Test", tmp_path / "projects"))
    page.start_render()
    qtbot.waitUntil(lambda: page.thread is None, timeout=5000)

    assert page.project.settings.workflow is WorkflowMode.EPIC_MONTAGE


def test_full_length_workflow_uses_library_table_and_tracks_selection(qtbot, tmp_path):
    page = WorkspacePage()
    qtbot.addWidget(page)
    project = create_project("Full Length Library", tmp_path / "projects")
    page.set_project(project)

    page.workflow_combo.setCurrentIndex(page.workflow_combo.findData(WorkflowMode.FULL_LENGTH))

    assert page.mode_stack.currentWidget() is page.full_panel
    assert page.full_song_search.placeholderText() == "Search songs, artists, or moods"
    assert page.full_song_table.horizontalHeaderItem(0).text() == "Song"
    assert page.full_song_table.rowCount() >= 4

    target_row = next(
        row
        for row in range(page.full_song_table.rowCount())
        if page.full_song_table.item(row, 0).data(Qt.ItemDataRole.UserRole) == "drone-music-2"
    )
    page.full_song_table.selectRow(target_row)
    assert project.settings.full_length_track_id == "drone-music-2"


def test_new_project_and_workflow_changes_select_default_songs(qtbot, tmp_path):
    page = WorkspacePage()
    qtbot.addWidget(page)
    project = create_project("Default Songs", tmp_path / "projects")
    page.set_project(project)

    assert project.settings.song_id == "epic-montage-1"
    assert page.song_table.currentRow() == 0
    assert page.song_table.item(0, 0).data(Qt.ItemDataRole.UserRole) == "epic-montage-1"
    epic_cell = page.song_table.cellWidget(0, 0)
    assert "background: #0e54a9" in epic_cell.styleSheet()
    assert "color: #ffffff" in epic_cell.title_label.styleSheet()

    page.workflow_combo.setCurrentIndex(page.workflow_combo.findData(WorkflowMode.FULL_LENGTH))
    first_full_length_id = page.full_song_table.item(0, 0).data(Qt.ItemDataRole.UserRole)
    assert page.full_song_table.currentRow() == 0
    assert project.settings.full_length_track_id == first_full_length_id
    full_cell = page.full_song_table.cellWidget(0, 0)
    assert "background: #0e54a9" in full_cell.styleSheet()
    assert "color: #ffffff" in full_cell.title_label.styleSheet()

    page.workflow_combo.setCurrentIndex(page.workflow_combo.findData(WorkflowMode.REAL_ESTATE))
    first_real_estate_id = page.re_song_table.item(0, 0).data(Qt.ItemDataRole.UserRole)
    assert page.re_song_table.currentRow() == 0
    assert project.settings.song_id == first_real_estate_id
    real_estate_cell = page.re_song_table.cellWidget(0, 0)
    assert "background: #0e54a9" in real_estate_cell.styleSheet()
    assert "color: #ffffff" in real_estate_cell.title_label.styleSheet()


def test_song_row_preview_toggles_play_pause_and_progress(qtbot):
    from PySide6.QtMultimedia import QMediaPlayer

    page = WorkspacePage()
    qtbot.addWidget(page)
    page.resize(900, 600)
    page.workspace_tabs.setCurrentIndex(1)
    page.show()
    cell = page.song_table.cellWidget(0, 0)

    assert isinstance(cell, SongPreviewCell)
    assert cell.play_button.width() == cell.play_button.height() == 34
    assert cell.play_button.icon().actualSize(cell.play_button.iconSize()) == cell.play_button.iconSize()
    page.song_table.selectRow(0)
    assert "color: #ffffff" in cell.title_label.styleSheet()
    assert "background: #0e54a9" in cell.styleSheet()
    assert cell.progress_slider.isHidden()

    qtbot.wait(50)
    resting_button_x = cell.play_button.x()
    cell.play_button.click()
    assert cell._progress_animation.state() == QAbstractAnimation.State.Running
    qtbot.waitUntil(
        lambda: page.song_preview_player.playbackState() == QMediaPlayer.PlaybackState.PlayingState,
        timeout=5000,
    )
    qtbot.waitUntil(
        lambda: cell._progress_animation.state() == QAbstractAnimation.State.Stopped,
        timeout=1000,
    )
    assert cell.play_button.toolTip() == "Stop"
    assert not cell.progress_slider.isHidden()
    assert cell.progress_slider.minimumHeight() >= 26
    assert cell.progress_slider.maximum() > 0
    assert cell.play_button.x() < resting_button_x
    rendered_cell = cell.grab().toImage()
    transport_sample = rendered_cell.pixelColor(
        min(rendered_cell.width() - 1, cell.play_button.geometry().right() + 6), 2,
    )
    assert transport_sample.name() == "#fcfcfc"
    assert rendered_cell.pixelColor(2, 2).name() == "#0e54a9"

    qtbot.mouseClick(
        cell.progress_slider,
        Qt.MouseButton.LeftButton,
        pos=QPoint(cell.progress_slider.width() * 3 // 5, cell.progress_slider.height() // 2),
    )
    target_position = cell.progress_slider.maximum() * 3 // 5
    qtbot.waitUntil(
        lambda: abs(page.song_preview_player.position() - target_position) < 1500,
        timeout=5000,
    )
    assert page.song_preview_player.playbackState() == QMediaPlayer.PlaybackState.PlayingState

    playing_button_x = cell.play_button.x()
    cell.play_button.click()
    assert cell._progress_animation.state() == QAbstractAnimation.State.Running
    assert not cell.progress_slider.isHidden()
    assert page.song_preview_player.playbackState() == QMediaPlayer.PlaybackState.StoppedState
    qtbot.waitUntil(
        lambda: cell._progress_animation.state() == QAbstractAnimation.State.Stopped,
        timeout=1000,
    )
    assert cell.play_button.toolTip() == "Play"
    assert cell.progress_slider.isHidden()
    assert cell.play_button.x() > playing_button_x
    assert abs(cell.play_button.x() - resting_button_x) <= 2
    assert page.song_preview_player.position() == 0


def test_click_seek_slider_emits_clicked_position(qtbot):
    slider = ClickSeekSlider(Qt.Orientation.Horizontal)
    qtbot.addWidget(slider)
    slider.setRange(0, 1000)
    slider.resize(400, 30)
    slider.show()
    requested = []
    slider.position_requested.connect(requested.append)

    qtbot.mouseClick(slider, Qt.MouseButton.LeftButton, pos=QPoint(300, 15))

    assert requested
    assert requested[-1] == pytest.approx(750, abs=5)
    assert slider.value() == requested[-1]


def test_cut_table_and_waveform_selection_stay_synchronized(qtbot):
    dialog = SongEditorDialog(AlphaEntitlementProvider())
    qtbot.addWidget(dialog)
    epic_row = next(
        row for row, song in enumerate(dialog.filtered_songs)
        if song.song_id == "epic-montage-1"
    )
    dialog._load_selected(epic_row)
    dialog.current.readonly = False
    dialog._set_editable(True)
    dialog.cut_markers.select_row(3)
    assert dialog.waveform.selected_marker_index == 3

    original_count = len(dialog.cut_markers.values())
    dialog.move_cut_timestamp(3, 40.0)
    assert 40.0 in dialog.cut_markers.values()
    assert dialog.waveform.selected_marker_index == dialog.cut_markers.values().index(40.0)
    dialog.remove_cut_timestamp(dialog.cut_markers.values().index(40.0))
    assert len(dialog.cut_markers.values()) == original_count - 1


def test_song_editor_space_shortcut_is_limited_to_cuts_tab(qtbot):
    dialog = SongEditorDialog(AlphaEntitlementProvider())
    qtbot.addWidget(dialog)
    dialog.show()
    dialog.current.readonly = False
    dialog._set_editable(True)
    toggles = []
    dialog.toggle_playback = lambda: toggles.append(True)
    dialog.tabs.setCurrentIndex(0)
    dialog.title_edit.setText("Epic")
    dialog.title_edit.setFocus()
    dialog.title_edit.setCursorPosition(len(dialog.title_edit.text()))
    qtbot.keyClick(dialog.title_edit, Qt.Key.Key_Space)
    assert toggles == []
    assert dialog.title_edit.text() == "Epic "
    dialog.tabs.setCurrentIndex(1)
    dialog.cut_markers.table.setFocus()
    qtbot.keyClick(dialog.cut_markers.table, Qt.Key.Key_Space)
    assert toggles == [True]


def test_song_editor_uses_compact_ten_row_cut_table(qtbot):
    dialog = SongEditorDialog(AlphaEntitlementProvider())
    qtbot.addWidget(dialog)
    row_height = dialog.cut_markers.table.verticalHeader().defaultSectionSize()
    body_height = dialog.cut_markers.table.height() - dialog.cut_markers.table.horizontalHeader().sizeHint().height()
    assert dialog.height() == 700
    assert row_height == 31
    assert 10 * row_height <= body_height <= 10 * row_height + 8


def test_results_list_visibility_flow(qtbot, tmp_path, monkeypatch):
    from e2dm2.models import OutputResult

    class FakeRenderWorker(QObject):
        progress = Signal(object)
        finished = Signal(object)
        failed = Signal(str)

        def __init__(self, project, request, cancellation):
            super().__init__()

        @Slot()
        def run(self):
            outputs = [OutputResult("out1", "path1.mp4", True)]
            self.finished.emit(RenderResult(outputs))

    monkeypatch.setattr("e2dm2.ui.RenderWorker", FakeRenderWorker)
    page = WorkspacePage()
    qtbot.addWidget(page)
    
    # 1. Initially hidden
    assert page.results_list.isHidden()
    
    page.set_project(create_project("Visibility Test", tmp_path / "projects"))
    assert page.results_list.isHidden()
    
    page.start_render()
    # During render, it should remain hidden
    assert page.results_list.isHidden()
    
    qtbot.waitUntil(lambda: page.thread is None, timeout=5000)

    # 2. Once finished with outputs, it should be visible
    assert not page.results_list.isHidden()
    assert page.results_list.count() == 1

    # 3. Starting a new render should hide it again
    page.start_render()
    assert page.results_list.isHidden()
    qtbot.waitUntil(lambda: page.thread is None, timeout=5000)


def test_timecode_helpers_use_millisecond_precision():
    assert format_timecode(3_723_045) == "01:02:03.045"
    assert parse_timecode("01:02:03.045") == 3_723_045
    with pytest.raises(ValueError, match="HH:MM:SS.mmm"):
        parse_timecode("1:02")


def test_preview_draft_only_commits_on_save(qtbot, tmp_path):
    media = MediaItem("source/test.mp4", "test.mp4", 320, 180, 30, 30, "h264", 1)
    dialog = ClipPreviewDialog(media, str(tmp_path / "missing.mp4"))
    qtbot.addWidget(dialog)
    dialog.create_selection(SelectionType.EXCLUDE, 1000, 2000)
    assert media.selections == []
    dialog.reject()
    assert media.selections == []

    saved = ClipPreviewDialog(media, str(tmp_path / "missing.mp4"))
    qtbot.addWidget(saved)
    saved.create_selection(SelectionType.REQUIRED, 3000, 23_000)
    saved.save_and_accept()
    assert media.selections == [ClipSelection(SelectionType.REQUIRED, 3000, 23_000)]


def test_selected_range_can_be_deleted_without_inspector_controls(qtbot, tmp_path):
    media = MediaItem(
        "source/test.mp4", "test.mp4", 320, 180, 30, 30, "h264", 1,
        [ClipSelection(SelectionType.EXCLUDE, 1000, 2000)],
    )
    dialog = ClipPreviewDialog(media, str(tmp_path / "missing.mp4"))
    qtbot.addWidget(dialog)
    dialog.show()
    dialog.select_selection(0)
    qtbot.keyClick(dialog.selection_table, Qt.Key.Key_Delete)
    assert dialog.draft == []


def test_footage_table_displays_mark_counts(qtbot, tmp_path):
    page = WorkspacePage()
    qtbot.addWidget(page)
    project = create_project("Badges", tmp_path / "projects")
    project.settings.media = [MediaItem(
        "source/test.mp4", "test.mp4", 320, 180, 30, 30, "h264", 1,
        [ClipSelection(SelectionType.EXCLUDE, 0, 1000), ClipSelection(SelectionType.REQUIRED, 2000, 3000)],
    )]
    page.set_project(project)
    assert page.media_table.item(0, 1).text() == "R 1 / G 1"


def test_combined_timeline_hovers_and_drag_creates_selection(qtbot):
    timeline = SelectionTimeline(60_000)
    timeline.resize(1000, 96)
    qtbot.addWidget(timeline)
    timeline.show()
    previewed = []
    created = []
    timeline.positionPreviewed.connect(previewed.append)
    timeline.rangeCreated.connect(lambda kind, start, end: created.append((kind, start, end)))

    qtbot.mouseMove(timeline, QPoint(500, 45))
    assert previewed[-1] == pytest.approx(30_000, abs=100)
    assert timeline.hover_ms == previewed[-1]

    qtbot.mousePress(timeline, Qt.MouseButton.LeftButton, pos=QPoint(200, 45))
    qtbot.mouseMove(timeline, QPoint(400, 45))
    qtbot.mouseRelease(timeline, Qt.MouseButton.LeftButton, pos=QPoint(400, 45))
    assert len(created) == 1
    assert created[0][0] is SelectionType.EXCLUDE
    assert created[0][1] < created[0][2]


def test_preview_dialog_uses_timeline_as_its_scrubber(qtbot, tmp_path):
    media = MediaItem("source/test.mp4", "test.mp4", 320, 180, 30, 30, "h264", 1)
    dialog = ClipPreviewDialog(media, str(tmp_path / "missing.mp4"))
    qtbot.addWidget(dialog)
    assert dialog.height() == 620
    assert dialog.minimumSizeHint().height() <= 620
    table_body_height = (
        dialog.selection_table.maximumHeight()
        - dialog.selection_table.horizontalHeader().sizeHint().height()
        - dialog.selection_table.frameWidth() * 2
    )
    assert table_body_height >= dialog.selection_table.verticalHeader().defaultSectionSize() * 5
    assert not hasattr(dialog, "scrubber")
    dialog.timeline.positionPreviewed.emit(1500)
    assert dialog.timeline.playhead_ms == 1500


def test_fullscreen_keeps_only_video_controls_and_timeline(qtbot, tmp_path):
    media = MediaItem("source/test.mp4", "test.mp4", 320, 180, 30, 30, "h264", 1)
    dialog = ClipPreviewDialog(media, str(tmp_path / "missing.mp4"))
    qtbot.addWidget(dialog)
    dialog.show()
    original_geometry = dialog.geometry()

    dialog.toggle_fullscreen()
    qtbot.waitUntil(dialog.isFullScreen)
    assert dialog.video.isVisible()
    assert dialog.timeline.isVisible()
    assert dialog.exclude_tool.isVisible()
    assert dialog.required_tool.isVisible()
    assert dialog.selection_table.isHidden()
    assert dialog.button_box.isHidden()
    assert dialog.fullscreen_button.text() == "Exit Full Screen"
    dialog.create_selection(SelectionType.EXCLUDE, 1000, 2000)
    assert len(dialog.draft) == 1

    dialog.exit_fullscreen()
    qtbot.waitUntil(lambda: not dialog.isFullScreen())
    assert not dialog.selection_table.isHidden()
    assert not dialog.button_box.isHidden()
    assert dialog.fullscreen_button.text() == "Full Screen"
    assert dialog.geometry() == original_geometry


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="FFmpeg is required")
def test_first_hover_silently_initializes_video_preview(qtbot, tmp_path):
    source = tmp_path / "hover-preview.mp4"
    subprocess.run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
        "-i", "testsrc2=s=320x180:r=30:d=1", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(source),
    ], check=True)
    media = MediaItem("source/hover-preview.mp4", source.name, 320, 180, 30, 1, "h264", source.stat().st_size)
    dialog = ClipPreviewDialog(media, str(source))
    qtbot.addWidget(dialog)
    dialog.show()

    dialog.timeline.positionPreviewed.emit(600)
    qtbot.waitUntil(
        lambda: dialog._preview_ready and not dialog._hover_warming and abs(dialog.player.position() - 600) <= 100,
        timeout=5000,
    )
    assert dialog.player.playbackState() is not dialog.player.PlaybackState.PlayingState
    assert not dialog.audio.isMuted()


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="FFmpeg is required")
def test_preview_builds_and_reuses_fast_proxy(qtbot, tmp_path):
    source = tmp_path / "proxy-source.mp4"
    proxy = tmp_path / "cache" / "proxy.preview.mp4"
    subprocess.run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
        "-i", "testsrc2=s=1280x720:r=60:d=1", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(source),
    ], check=True)
    media = MediaItem("source/proxy-source.mp4", source.name, 1280, 720, 60, 1, "h264", source.stat().st_size)
    dialog = ClipPreviewDialog(media, str(source), proxy_path=str(proxy))
    qtbot.addWidget(dialog)
    dialog.show()
    assert not dialog.proxy_progress.isHidden()
    qtbot.waitUntil(lambda: dialog.proxy_process is None, timeout=10_000)
    assert proxy.is_file()
    assert dialog.proxy_progress.value() == 100
    assert dialog.proxy_progress.format() == "Fast preview ready"

    probe = subprocess.run([
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=width,r_frame_rate", "-of", "json", str(proxy),
    ], capture_output=True, text=True, check=True)
    stream = json.loads(probe.stdout)["streams"][0]
    assert stream["width"] <= 854
    assert stream["r_frame_rate"] == "30/1"

    cached = ClipPreviewDialog(media, str(source), proxy_path=str(proxy))
    qtbot.addWidget(cached)
    assert cached.proxy_process is None
    assert Path(cached.player.source().toLocalFile()) == proxy


def test_splash_screen(qtbot):
    from e2dm2.ui import AppSplashScreen
    from PySide6.QtWidgets import QLabel
    splash = AppSplashScreen()
    qtbot.addWidget(splash)
    splash.show()
    
    # Assert elements exist and have correct labels/properties
    assert splash.logo_label is not None
    
    # Find child elements and assert their properties
    title = splash.findChild(QLabel, "splashTitle")
    assert title is None
    
    version = splash.findChild(QLabel, "splashVersion")
    assert version is not None
    assert version.text() == "Version 1.0"
    
    status = splash.findChild(QLabel, "splashStatus")
    assert status is not None
    assert status.text() == "Initializing workflows..."
    
    # The splash screen should start visible
    assert splash.isVisible()
