import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QAbstractAnimation, QObject, QPoint, QSettings, QSize, Qt, Signal, Slot
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QLabel, QMessageBox, QProgressBar, QProgressDialog, QTabWidget, QTableWidget, QTableWidgetItem, QWidget, QDialogButtonBox

from e2dm2.models import ClipSelection, MediaItem, RenderResult, SelectionType, WorkflowMode
from e2dm2.preview import ClipPreviewDialog, SelectionTimeline, format_timecode, parse_timecode
from e2dm2.editor import SongEditorDialog
from e2dm2.entitlements import AlphaEntitlementProvider
from e2dm2.ui import ClickSeekSlider, FullRowSelectionDelegate, HomePage, MainWindow, OptionsDialog, STYLESHEET, SongPreviewCell, splash_screen_enabled
from e2dm2.project import create_project, load_project
from e2dm2.ui import WorkspacePage, _duration


def test_main_window_smoke(qtbot):
    window = MainWindow()
    qtbot.addWidget(window)
    assert window.minimumWidth() >= 1024
    assert window.minimumHeight() >= 700
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


def test_main_window_can_launch_maximized_on_active_screen(qtbot):
    window = MainWindow()
    qtbot.addWidget(window)

    window.show_maximized_on_active_screen()

    assert window.isMaximized()
    assert window._centered_once


def test_tab_strip_matches_window_background(qtbot):
    tabs = QTabWidget()
    qtbot.addWidget(tabs)
    tabs.setStyleSheet(STYLESHEET)
    tabs.addTab(QWidget(), "First")
    tabs.addTab(QWidget(), "Second")
    tabs.show()

    background = tabs.tabBar().palette().color(QPalette.ColorRole.Window)
    assert background.name() == "#f5f7f8"


def test_progress_percentage_text_is_black(qtbot):
    progress = QProgressBar()
    qtbot.addWidget(progress)
    progress.setStyleSheet(STYLESHEET)
    progress.setValue(84)
    progress.show()

    text_color = progress.palette().color(QPalette.ColorRole.Text)
    assert text_color.name() == "#000000"


def test_import_status_does_not_repeat_progress_percentage(qtbot):
    page = WorkspacePage()
    qtbot.addWidget(page)
    page.import_dialog = QProgressDialog("", "Cancel", 0, 100, page)

    page.import_progress(94, "DJI_001.mp4")

    assert page.import_dialog.labelText() == "Importing DJI_001.mp4"
    assert page.import_dialog.value() == 94


def test_footage_action_controls_have_matching_heights(qtbot):
    page = WorkspacePage()
    qtbot.addWidget(page)
    page.resize(900, 600)
    page.show()

    expected_height = page.add_files_button.height()
    assert page.add_folder_button.height() == expected_height
    assert page.preview_button.height() == expected_height
    assert page.move_up_button.height() == expected_height
    assert page.move_down_button.height() == expected_height
    assert page.remove_button.height() == expected_height
    assert page.media_total.height() == expected_height

    remove_icon = page.remove_button.icon().pixmap(page.remove_button.iconSize()).toImage()
    has_red_pixel = any(
        remove_icon.pixelColor(x, y).alpha() > 0
        and remove_icon.pixelColor(x, y).red() > remove_icon.pixelColor(x, y).green() * 1.5
        for x in range(remove_icon.width())
        for y in range(remove_icon.height())
    )
    assert has_red_pixel


def test_footage_selection_is_painted_as_a_full_row(qtbot):
    page = WorkspacePage()
    qtbot.addWidget(page)
    table = page.media_table
    table.setRowCount(1)
    for column in range(table.columnCount()):
        table.setItem(0, column, QTableWidgetItem(str(column)))

    table.setCurrentCell(0, 2)

    assert table.selectionBehavior() == QTableWidget.SelectionBehavior.SelectRows
    assert isinstance(table.itemDelegate(), FullRowSelectionDelegate)
    assert {index.column() for index in table.selectionModel().selectedIndexes()} == set(range(table.columnCount()))


def test_music_library_selection_is_painted_as_a_full_row(qtbot):
    page = WorkspacePage()
    qtbot.addWidget(page)
    tables = (
        page.song_table,
        page.full_song_table,
        page.re_song_table,
        page.custom_song_table,
    )

    for table in tables:
        assert table.selectionBehavior() == QTableWidget.SelectionBehavior.SelectRows
        assert isinstance(table.itemDelegate(), FullRowSelectionDelegate)

    page.song_table.setCurrentCell(0, 2)
    assert {index.column() for index in page.song_table.selectionModel().selectedIndexes()} == {0, 1, 2, 3}


def test_hero_shows_created_then_selected_soundtrack_target_duration(qtbot, tmp_path):
    page = WorkspacePage()
    qtbot.addWidget(page)
    page.set_project(create_project("Hero Metrics", tmp_path / "projects"))
    page.resize(900, 600)
    page.show()

    captions = [
        label.text()
        for label in page.findChildren(QLabel)
        if label.objectName() == "metricCaption"
    ]
    assert captions == ["Created", "Target Duration"]
    hero_icons = [
        label
        for label in page.findChildren(QLabel)
        if label.objectName() == "heroIcon"
    ]
    assert len(hero_icons) == 3
    assert all(label.pixmap() is not None and not label.pixmap().isNull() for label in hero_icons)
    assert page.findChild(QLabel, "heroSoundtrackCaption") is None

    for label in hero_icons:
        image = label.pixmap().toImage()
        colored_pixels = [
            image.pixelColor(x, y)
            for x in range(image.width())
            for y in range(image.height())
                if image.pixelColor(x, y).alpha() > 200
        ]
        assert colored_pixels
        assert all(color.blue() > color.green() > color.red() for color in colored_pixels)

    selected_song_id = page.project.settings.song_id
    selected_song = next(song for song in page.songs if song.song_id == selected_song_id)
    assert page.metric_target_duration_value.text() == _duration(selected_song.total_duration_seconds)

    page.song_table.selectRow(1)
    newly_selected_song_id = page.project.settings.song_id
    newly_selected_song = next(song for song in page.songs if song.song_id == newly_selected_song_id)
    assert page.metric_target_duration_value.text() == _duration(newly_selected_song.total_duration_seconds)


def test_sidebar_uses_full_brand_logo(qtbot):
    page = WorkspacePage()
    qtbot.addWidget(page)

    logo = page.sidebar_logo_label.pixmap()
    assert logo is not None
    assert not logo.isNull()
    assert logo.size() == QSize(315, 192)
    assert page.sidebar_logo_label.size() == logo.deviceIndependentSize().toSize()
    assert page.findChild(QLabel, "sidebarBrand") is None
    assert page.findChild(QLabel, "sidebarTagline") is None


def test_project_title_can_be_edited_inline_and_persisted(qtbot, tmp_path):
    page = WorkspacePage()
    qtbot.addWidget(page)
    project = create_project("Original Title", tmp_path / "projects")
    page.set_project(project)
    page.show()

    page.project_title_edit_button.click()
    assert page.project_title.isHidden()
    assert page.project_title_edit.isVisible()
    qtbot.waitUntil(page.project_title_edit.hasFocus)

    page.project_title_edit.setText("New Project Title")
    qtbot.keyClick(page.project_title_edit, Qt.Key.Key_Return)

    assert page.project_title.text() == "New Project Title"
    assert project.settings.name == "New Project Title"
    assert load_project(project.path).settings.name == "New Project Title"
    assert page.project_title_edit.isHidden()
    assert page.project_title_edit_button.isVisible()

    page.project_title_edit_button.click()
    page.project_title_edit.setText("Discarded Title")
    qtbot.keyClick(page.project_title_edit, Qt.Key.Key_Escape)
    assert page.project_title.text() == "New Project Title"
    assert project.settings.name == "New Project Title"


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

    # Verify tabs exist and are correctly named
    assert dialog.tab_widget.count() == 2
    assert dialog.tab_widget.tabText(0) == "General"
    assert dialog.tab_widget.tabText(1) == "Codec Settings"

    # Verify initial Codec Settings tab values
    assert dialog.codec_combo.currentText() == "H.264 (AVC)"
    assert dialog.quality_slider.value() == 80
    assert dialog.quality_val_label.text() == "80%"
    assert dialog.compression_combo.currentText() == "Medium (Standard)"
    assert dialog.hw_accel_checkbox.isChecked() is True

    # Test changing codec settings and verification of settings persistence
    dialog.codec_combo.setCurrentText("H.265 (HEVC)")
    assert settings.value("codec") == "H.265 (HEVC)"

    dialog.quality_slider.setValue(90)
    assert int(settings.value("quality")) == 90
    assert dialog.quality_val_label.text() == "90%"

    dialog.compression_combo.setCurrentText("High (Slow render, smaller file)")
    assert settings.value("compression") == "High (Slow render, smaller file)"

    dialog.hw_accel_checkbox.setChecked(False)
    assert settings.value("hardware_acceleration") in (False, "false")


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
    assert page.recent_list.selectionBehavior() == QTableWidget.SelectionBehavior.SelectRows
    assert isinstance(page.recent_list.itemDelegate(), FullRowSelectionDelegate)


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
    target_song = next(song for song in page.songs if song.song_id == "drone-music-2")
    assert page.metric_target_duration_value.text() == _duration(target_song.total_duration_seconds)


def test_soundtrack_dropdown_popups_use_light_surface(qtbot):
    page = WorkspacePage()
    qtbot.addWidget(page)
    page.resize(900, 600)
    page.show()

    combos = [
        page.workflow_combo,
        page.mood_filter,
        page.energy_filter,
        page.full_mood_filter,
        page.full_energy_filter,
        page.re_mood_filter,
        page.re_energy_filter,
        page.custom_mood_filter,
        page.custom_energy_filter,
    ]
    for combo in combos:
        combo.showPopup()
        popup_style = combo.view().window().styleSheet()
        assert "background-color: #FFFFFF" in popup_style
        assert "border: 1px solid #DDE5E7" in popup_style
        content_height = sum(combo.view().sizeHintForRow(row) for row in range(combo.count()))
        assert combo.view().viewport().height() >= content_height
        combo.hidePopup()


def test_new_project_and_workflow_changes_select_default_songs(qtbot, tmp_path):
    page = WorkspacePage()
    qtbot.addWidget(page)
    project = create_project("Default Songs", tmp_path / "projects")
    page.set_project(project)

    assert project.settings.song_id == "epic-montage-1"
    assert page.song_table.currentRow() == 0
    assert page.song_table.item(0, 0).data(Qt.ItemDataRole.UserRole) == "epic-montage-1"
    epic_cell = page.song_table.cellWidget(0, 0)
    assert "background: #EAF2FC" in epic_cell.styleSheet()
    assert "color: #0E56AA" in epic_cell.title_label.styleSheet()

    page.workflow_combo.setCurrentIndex(page.workflow_combo.findData(WorkflowMode.FULL_LENGTH))
    first_full_length_id = page.full_song_table.item(0, 0).data(Qt.ItemDataRole.UserRole)
    assert page.full_song_table.currentRow() == 0
    assert project.settings.full_length_track_id == first_full_length_id
    full_cell = page.full_song_table.cellWidget(0, 0)
    assert "background: #EAF2FC" in full_cell.styleSheet()
    assert "color: #0E56AA" in full_cell.title_label.styleSheet()

    page.workflow_combo.setCurrentIndex(page.workflow_combo.findData(WorkflowMode.REAL_ESTATE))
    first_real_estate_id = page.re_song_table.item(0, 0).data(Qt.ItemDataRole.UserRole)
    assert page.re_song_table.currentRow() == 0
    assert project.settings.song_id == first_real_estate_id
    real_estate_cell = page.re_song_table.cellWidget(0, 0)
    assert "background: #EAF2FC" in real_estate_cell.styleSheet()
    assert "color: #0E56AA" in real_estate_cell.title_label.styleSheet()


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
    assert "color: #0E56AA" in cell.title_label.styleSheet()
    assert "background: #EAF2FC" in cell.styleSheet()
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
    assert transport_sample.name() == "#eaf2fc"
    assert rendered_cell.pixelColor(2, 2).name() == "#eaf2fc"

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
    assert page.media_table.item(0, 2).text() == "R 1 / G 1"


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
    assert dialog.height() >= 660
    assert dialog.minimumSizeHint().height() <= dialog.height()
    table_body_height = (
        dialog.selection_table.maximumHeight()
        - dialog.selection_table.horizontalHeader().sizeHint().height()
        - dialog.selection_table.frameWidth() * 2
    )
    assert table_body_height >= dialog.selection_table.verticalHeader().defaultSectionSize() * 4
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
    assert dialog.selection_mode_panel.isVisible()
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
    assert dialog.height() == original_geometry.height()


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


def test_sidebar_navigation_changes_workspace_pages(qtbot):
    page = WorkspacePage()
    qtbot.addWidget(page)
    page.show()
    qtbot.waitUntil(page.nav_selection_indicator.isVisible)

    page.nav_soundtrack.click()
    assert page.workspace_tabs.currentIndex() == 1
    assert page._nav_highlight_animation.state() == QAbstractAnimation.State.Running
    qtbot.waitUntil(
        lambda: page._nav_highlight_animation.state() == QAbstractAnimation.State.Stopped,
        timeout=1000,
    )
    assert page.nav_selection_highlight.geometry() == page.nav_soundtrack.geometry()
    assert page.nav_soundtrack.property("active")

    page.nav_produce.click()
    assert page.workspace_tabs.currentIndex() == 2

    page.nav_footage.click()
    assert page.workspace_tabs.currentIndex() == 0


def test_preview_dialog_default_paint_mode_is_visually_exclude(qtbot, tmp_path):
    media = MediaItem("source/test.mp4", "test.mp4", 320, 180, 30, 30, "h264", 1)
    dialog = ClipPreviewDialog(media, str(tmp_path / "missing.mp4"))
    qtbot.addWidget(dialog)

    assert dialog.timeline.tool is SelectionType.EXCLUDE
    assert dialog.exclude_tool.isChecked()
    assert not dialog.required_tool.isChecked()
    assert dialog.exclude_tool.property("modeActive") == "true"
    assert dialog.required_tool.property("modeActive") == "false"
    assert "EXCLUDE" in dialog.current_mode_title.text()


def test_preview_dialog_required_button_updates_active_paint_mode(qtbot, tmp_path):
    media = MediaItem("source/test.mp4", "test.mp4", 320, 180, 30, 30, "h264", 1)
    dialog = ClipPreviewDialog(media, str(tmp_path / "missing.mp4"))
    qtbot.addWidget(dialog)

    qtbot.mouseClick(dialog.required_tool, Qt.MouseButton.LeftButton)

    assert dialog.timeline.tool is SelectionType.REQUIRED
    assert dialog.required_tool.isChecked()
    assert not dialog.exclude_tool.isChecked()
    assert dialog.required_tool.property("modeActive") == "true"
    assert dialog.exclude_tool.property("modeActive") == "false"
    assert "REQUIRED" in dialog.current_mode_title.text()


def test_required_paint_mode_creates_required_selection(qtbot):
    timeline = SelectionTimeline(60_000)
    timeline.resize(1000, 120)
    qtbot.addWidget(timeline)
    timeline.show()

    created = []
    timeline.rangeCreated.connect(lambda kind, start, end: created.append((kind, start, end)))

    timeline.set_tool(SelectionType.REQUIRED)

    qtbot.mousePress(timeline, Qt.MouseButton.LeftButton, pos=QPoint(200, 50))
    qtbot.mouseMove(timeline, QPoint(400, 50))
    qtbot.mouseRelease(timeline, Qt.MouseButton.LeftButton, pos=QPoint(400, 50))

    assert len(created) == 1
    assert created[0][0] is SelectionType.REQUIRED
    assert created[0][2] > created[0][1]


def test_selection_timeline_cursor_changes_on_hover_handles(qtbot):
    timeline = SelectionTimeline(60_000)
    timeline.resize(1000, 96)
    selection = ClipSelection(SelectionType.EXCLUDE, 10000, 20000)
    timeline.set_selections([selection], 0)
    qtbot.addWidget(timeline)
    timeline.show()

    start_x = timeline._x_for_ms(10000)
    qtbot.mouseMove(timeline, QPoint(round(start_x), 45))
    assert timeline.cursor().shape() == Qt.CursorShape.SizeHorCursor

    mid_x = timeline._x_for_ms(15000)
    qtbot.mouseMove(timeline, QPoint(round(mid_x), 45))
    assert timeline.cursor().shape() == Qt.CursorShape.PointingHandCursor

    outside_x = timeline._x_for_ms(5000)
    qtbot.mouseMove(timeline, QPoint(round(outside_x), 45))
    assert timeline.cursor().shape() == Qt.CursorShape.ArrowCursor


def test_click_near_edge_resizes_existing_selection_instead_of_creating_new_one(qtbot):
    timeline = SelectionTimeline(60_000)
    timeline.resize(1000, 96)
    selection = ClipSelection(SelectionType.EXCLUDE, 10000, 20000)
    timeline.set_selections([selection])
    qtbot.addWidget(timeline)
    timeline.show()

    edited = []
    created = []
    timeline.rangeEdited.connect(lambda idx, start, end: edited.append((idx, start, end)))
    timeline.rangeCreated.connect(lambda kind, start, end: created.append((kind, start, end)))

    start_x = timeline._x_for_ms(10000)
    qtbot.mousePress(timeline, Qt.MouseButton.LeftButton, pos=QPoint(round(start_x - 5), 45))
    qtbot.mouseMove(timeline, QPoint(round(start_x - 50), 45))
    qtbot.mouseRelease(timeline, Qt.MouseButton.LeftButton, pos=QPoint(round(start_x - 50), 45))

    assert len(edited) == 1
    assert edited[0][0] == 0
    assert len(created) == 0


def test_drag_middle_of_selection_slides_it(qtbot):
    timeline = SelectionTimeline(60_000)
    timeline.resize(1000, 96)
    selection = ClipSelection(SelectionType.EXCLUDE, 10000, 20000)
    timeline.set_selections([selection])
    qtbot.addWidget(timeline)
    timeline.show()

    edited = []
    timeline.rangeEdited.connect(lambda idx, start, end: edited.append((idx, start, end)))

    mid_x = timeline._x_for_ms(15000)
    drag_x = timeline._x_for_ms(20000)

    qtbot.mouseMove(timeline, QPoint(round(mid_x), 45))
    assert timeline.cursor().shape() == Qt.CursorShape.PointingHandCursor
    qtbot.mousePress(timeline, Qt.MouseButton.LeftButton, pos=QPoint(round(mid_x), 45))

    qtbot.mouseMove(timeline, QPoint(round(drag_x), 45))
    qtbot.mouseRelease(timeline, Qt.MouseButton.LeftButton, pos=QPoint(round(drag_x), 45))

    assert len(edited) == 1
    assert edited[0][0] == 0
    assert abs(edited[0][1] - 15000) <= 200
    assert abs(edited[0][2] - 25000) <= 200


def test_clip_preview_dialog_redesign(qtbot, tmp_path):
    media = MediaItem(
        "source/test.mp4", "test.mp4", 320, 180, 30, 30, "h264", 1,
        [ClipSelection(SelectionType.EXCLUDE, 1000, 2000)],
    )
    dialog = ClipPreviewDialog(media, str(tmp_path / "missing.mp4"))
    qtbot.addWidget(dialog)
    dialog.show()

    # Verify column count and headers
    assert dialog.selection_table.columnCount() == 5
    headers = [dialog.selection_table.horizontalHeaderItem(i).text() for i in range(5)]
    assert headers == ["#", "Type", "Start", "End", "Duration"]

    # Verify table content population (row index centered, icon set)
    num_item = dialog.selection_table.item(0, 0)
    assert num_item.text() == "1"
    assert num_item.textAlignment() == Qt.AlignmentFlag.AlignCenter

    type_item = dialog.selection_table.item(0, 1)
    assert type_item.text() == "Exclude"
    assert not type_item.icon().isNull()

    # Verify timeline help text contains circled info icon
    assert "ⓘ" in dialog.timeline_help_label.text()

    # Verify buttons have correct objectNames
    assert dialog.play_button.objectName() == "playButton"
    assert dialog.fullscreen_button.objectName() == "fullscreenButton"

    save_btn = dialog.button_box.button(QDialogButtonBox.StandardButton.Save)
    cancel_btn = dialog.button_box.button(QDialogButtonBox.StandardButton.Cancel)
    assert save_btn.objectName() == "saveButton"
    assert cancel_btn.objectName() == "cancelButton"

    # Verify inner layout widgets for Exclude and Required tools
    assert dialog.exclude_title_label.text() == "Exclude"
    assert dialog.required_title_label.text() == "Required"


def test_smooth_table_widget_drag_drop(qtbot):
    from PySide6.QtCore import QMimeData, QUrl, Qt, QPoint
    from PySide6.QtGui import QDropEvent
    from e2dm2.ui import SmoothTableWidget
    import tempfile
    
    table = SmoothTableWidget(0, 9)
    qtbot.addWidget(table)
    
    assert table.acceptDrops()
    
    # Create temp files
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f1, \
         tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f2:
        path1 = Path(f1.name)
        path2 = Path(f2.name)
        
    try:
        # Simulate drop event
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(path1)), QUrl.fromLocalFile(str(path2))])
        
        dropped_paths = []
        table.filesDropped.connect(dropped_paths.extend)
        
        # Trigger dropEvent
        event = QDropEvent(QPoint(10, 10), Qt.DropAction.CopyAction, mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        table.dropEvent(event)
        
        # Only the .mp4 file should be imported
        assert len(dropped_paths) == 1
        assert dropped_paths[0] == path1
    finally:
        if path1.exists():
            path1.unlink()
        if path2.exists():
            path2.unlink()


def test_smooth_table_widget_delete_keys(qtbot):
    from PySide6.QtCore import Qt
    from e2dm2.ui import SmoothTableWidget
    
    table = SmoothTableWidget(0, 9)
    qtbot.addWidget(table)
    
    delete_called = 0
    def on_delete():
        nonlocal delete_called
        delete_called += 1
        
    table.deleteRequested.connect(on_delete)
    
    # Send Delete key event
    qtbot.keyClick(table, Qt.Key.Key_Delete)
    assert delete_called == 1
    
    # Send Backspace key event
    qtbot.keyClick(table, Qt.Key.Key_Backspace)
    assert delete_called == 2


def test_smooth_table_widget_clicked_empty(qtbot):
    from PySide6.QtCore import Qt, QPoint
    from PySide6.QtGui import QMouseEvent
    from e2dm2.ui import SmoothTableWidget
    
    table = SmoothTableWidget(0, 9)
    qtbot.addWidget(table)
    
    clicked_called = 0
    def on_clicked():
        nonlocal clicked_called
        clicked_called += 1
        
    table.clickedEmpty.connect(on_clicked)
    
    # Simulate mouse click on the empty viewport
    event = QMouseEvent(QMouseEvent.Type.MouseButtonPress, QPoint(10, 10), Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    table.mousePressEvent(event)
    assert clicked_called == 1


def test_waveform_widget_wheel_event(qtbot):
    from e2dm2.waveform import WaveformWidget, WaveformData
    from PySide6.QtCore import Qt, QPoint
    
    widget = WaveformWidget()
    qtbot.addWidget(widget)
    
    # Setup data
    widget.data = WaveformData(peaks=[0.0]*100, peaks_per_second=10.0, duration_seconds=10.0)
    widget.duration_seconds = 10.0
    widget.position_seconds = 5.0
    
    positions = []
    widget.position_requested.connect(positions.append)
    
    # Mock event class for wheel event
    class MockWheelEvent:
        def __init__(self, angle_delta_y, modifiers=Qt.KeyboardModifier.NoModifier):
            self._angle_delta = QPoint(0, angle_delta_y)
            self._modifiers = modifiers
            self._accepted = False
            
        def angleDelta(self):
            return self._angle_delta
            
        def modifiers(self):
            return self._modifiers
            
        def accept(self):
            self._accepted = True
            
    # 1. Test normal scroll up (forward)
    event1 = MockWheelEvent(120, Qt.KeyboardModifier.NoModifier)
    widget.wheelEvent(event1)
    assert event1._accepted
    assert len(positions) == 1
    assert pytest.approx(positions[-1]) == 5.1
    
    # 2. Test normal scroll down (backward)
    event2 = MockWheelEvent(-120, Qt.KeyboardModifier.NoModifier)
    widget.wheelEvent(event2)
    assert len(positions) == 2
    assert pytest.approx(positions[-1]) == 4.9
    
    # 3. Test precise scroll with Ctrl (ControlModifier)
    widget.position_seconds = 5.0
    event3 = MockWheelEvent(120, Qt.KeyboardModifier.ControlModifier)
    widget.wheelEvent(event3)
    assert len(positions) == 3
    assert pytest.approx(positions[-1]) == 5.01
    
    # 4. Test fast scroll with Shift (ShiftModifier)
    widget.position_seconds = 5.0
    event4 = MockWheelEvent(120, Qt.KeyboardModifier.ShiftModifier)
    widget.wheelEvent(event4)
    assert len(positions) == 4
    assert pytest.approx(positions[-1]) == 6.0
    
    # 5. Test boundary clamping (high boundary)
    widget.position_seconds = 9.95
    event5 = MockWheelEvent(120, Qt.KeyboardModifier.NoModifier) # moves by +0.1 -> 10.05 -> clamped to 10.0
    widget.wheelEvent(event5)
    assert len(positions) == 5
    assert pytest.approx(positions[-1]) == 10.0
    
    # 6. Test boundary clamping (low boundary)
    widget.position_seconds = 0.05
    event6 = MockWheelEvent(-120, Qt.KeyboardModifier.NoModifier) # moves by -0.1 -> -0.05 -> clamped to 0.0
    widget.wheelEvent(event6)
    assert len(positions) == 6
    assert pytest.approx(positions[-1]) == 0.0


def test_song_editor_button_styles(qtbot):
    from e2dm2.editor import SongEditorDialog
    from e2dm2.entitlements import AlphaEntitlementProvider
    from PySide6.QtWidgets import QPushButton
    
    dialog = SongEditorDialog(AlphaEntitlementProvider())
    qtbot.addWidget(dialog)
    
    assert dialog.new_button.objectName() == "newSongButton"
    assert dialog.duplicate_button.objectName() == "duplicateSongButton"
    assert dialog.delete_button.objectName() == "deleteSongButton"
    assert dialog.save_button.objectName() == "saveButton"
    
    close_button = dialog.findChild(QPushButton, "cancelButton")
    assert close_button is not None
    assert close_button.text() == "Close"
    
    # Check that custom stylesheet is set on the dialog
    assert "QPushButton#saveButton" in dialog.styleSheet()
    assert "#cancelButton" in dialog.styleSheet()
    assert "#playButton" in dialog.styleSheet()
    assert "#addPlayheadButton" in dialog.styleSheet()
    assert "QTableWidget::item" in dialog.styleSheet()
    assert "padding: 0px;" in dialog.styleSheet()

    # Check that cell widget content margins are 0
    from e2dm2.editor import ClickPassingWidget
    from PySide6.QtWidgets import QTableWidget
    table = QTableWidget(1, 2)
    label = QLabel("test")
    btn = QLabel("x")
    cell_widget = ClickPassingWidget(table, label, btn)
    assert cell_widget.layout().contentsMargins().top() == 0
    assert cell_widget.layout().contentsMargins().bottom() == 0

    # Check that comboboxes use SoundtrackComboBox
    from e2dm2.ui import SoundtrackComboBox
    assert isinstance(dialog.energy_combo, SoundtrackComboBox)
    assert isinstance(dialog.waveform_zoom, SoundtrackComboBox)

    # Check WorkflowSelectionDialog combo
    from e2dm2.editor import WorkflowSelectionDialog
    workflow_dlg = WorkflowSelectionDialog()
    qtbot.addWidget(workflow_dlg)
    assert isinstance(workflow_dlg.combo, SoundtrackComboBox)

    # Check that x_btn stylesheet uses color: #333333
    ts_w = dialog.cut_markers._create_timestamp_widget(5.0)
    assert "color: #333333;" in ts_w.x_btn.styleSheet()

    # Check that selection doesn't turn label text white
    dialog.cut_markers.add_value(10.0)
    dialog.cut_markers.select_row(0)
    selected_wrapper = dialog.cut_markers.table.cellWidget(0, 0)
    assert "color: #333333;" in selected_wrapper.label.styleSheet()

    # Check that position_slider has minimumHeight set to prevent clipping
    assert dialog.position_slider.minimumHeight() >= 28


def test_onboarding_overlay(qtbot):
    from e2dm2.onboarding import OnboardingOverlay, onboarding_enabled
    from PySide6.QtWidgets import QWidget
    from PySide6.QtCore import QSettings

    # Set initial state of settings for testing
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    app.setApplicationName("E2DM2")
    app.setOrganizationName("E2DM2")

    settings = QSettings()
    settings.setValue("startup/show_onboarding", True)
    settings.sync()

    # Create a parent widget with the target elements mock
    parent = QWidget()
    parent.new_button = QWidget(parent)
    parent.open_button = QWidget(parent)
    parent.recent_list = QWidget(parent)
    
    qtbot.addWidget(parent)
    parent.show()
    QApplication.processEvents()

    overlay = OnboardingOverlay(parent)

    # Show onboarding
    overlay.show_onboarding()
    QApplication.processEvents()
    assert overlay.isVisible()
    assert overlay.current_step == 0
    assert overlay.popup.title_label.text() == "New Project"

    # Go to next step
    overlay.next_step()
    assert overlay.current_step == 1
    assert overlay.popup.title_label.text() == "Open Project"

    # Go to next step
    overlay.next_step()
    assert overlay.current_step == 2
    assert overlay.popup.title_label.text() == "Recent Projects Section"

    # Go back
    overlay.prev_step()
    assert overlay.current_step == 1

    # Verify opt-out checkbox toggles the settings correctly
    assert not overlay.popup.opt_out_cb.isChecked()
    overlay.popup.opt_out_cb.setChecked(True)
    # Check that the setting is updated to False
    assert settings.value("startup/show_onboarding", True, type=bool) is False

    # Close tour
    overlay.next_step()  # Go to step 2 (index 2)
    overlay.next_step()  # Finish and trigger close_tour
    qtbot.wait(350)
    assert not overlay.isVisible()

    # Reset setting
    settings.setValue("startup/show_onboarding", True)
    settings.sync()


def test_welcome_dialog(qtbot):
    from e2dm2.onboarding import WelcomeDialog, welcome_modal_enabled
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    app.setApplicationName("E2DM2")
    app.setOrganizationName("E2DM2")

    settings = QSettings()
    settings.setValue("startup/show_welcome_modal", True)
    settings.sync()

    # Instantiate dialog
    dialog = WelcomeDialog()
    qtbot.addWidget(dialog)

    # Initially opt_out is unchecked
    assert not dialog.opt_out_cb.isChecked()

    # Check it
    dialog.opt_out_cb.setChecked(True)
    
    # Save settings check on reject
    dialog.reject()
    
    # Check that settings are updated
    assert settings.value("startup/show_welcome_modal", True, type=bool) is False

    # Restore settings
    settings.setValue("startup/show_welcome_modal", True)
    settings.sync()


def test_workspace_onboarding_overlay(qtbot):
    from e2dm2.onboarding import OnboardingOverlay, workspace_onboarding_enabled
    from e2dm2.ui import WorkspacePage
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    app.setApplicationName("E2DM2")
    app.setOrganizationName("E2DM2")

    settings = QSettings()
    settings.setValue("startup/show_workspace_onboarding", True)
    settings.sync()

    # Instantiate workspace page
    workspace = WorkspacePage()
    qtbot.addWidget(workspace)
    workspace.show()
    QApplication.processEvents()

    # Get onboarding steps
    steps = workspace.get_onboarding_steps()
    assert len(steps) == 8

    # Create overlay
    overlay = OnboardingOverlay(workspace, steps, "startup/show_workspace_onboarding")
    qtbot.addWidget(overlay)

    # Show onboarding
    overlay.show_onboarding()
    QApplication.processEvents()
    assert overlay.isVisible()
    assert overlay.current_step == 0
    assert overlay.popup.title_label.text() == "Three Sections, Three Steps"

    # Go through a few steps to ensure rect targets resolve correctly
    overlay.next_step()
    assert overlay.current_step == 1
    assert overlay.popup.title_label.text() == "Import files by Drag & Drop"

    overlay.next_step()
    assert overlay.current_step == 2
    assert overlay.popup.title_label.text() == "Import via Add Files / Folder"

    overlay.next_step()
    assert overlay.current_step == 3
    assert overlay.popup.title_label.text() == "Preview and Edit Clips"

    # Verify opt-out updates settings
    assert not overlay.popup.opt_out_cb.isChecked()
    overlay.popup.opt_out_cb.setChecked(True)
    assert settings.value("startup/show_workspace_onboarding", True, type=bool) is False

    # Reset settings
    settings.setValue("startup/show_workspace_onboarding", True)
    settings.sync()











