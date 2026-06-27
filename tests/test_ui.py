import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, QPoint, Qt, Signal, Slot
from PySide6.QtWidgets import QMessageBox

from e2dm2.models import ClipSelection, MediaItem, RenderResult, SelectionType, WorkflowMode
from e2dm2.preview import ClipPreviewDialog, SelectionTimeline, format_timecode, parse_timecode
from e2dm2.editor import SongEditorDialog
from e2dm2.entitlements import AlphaEntitlementProvider
from e2dm2.ui import HomePage, MainWindow
from e2dm2.project import create_project
from e2dm2.ui import WorkspacePage


def test_main_window_smoke(qtbot):
    window = MainWindow()
    qtbot.addWidget(window)
    assert window.size().width() == 820
    assert window.size().height() == 540
    window.show()
    assert window.windowTitle().startswith("Easy Epic Drone Movie Maker")
    assert window.workspace.song_table.rowCount() >= 2
    assert window.home.recent_list is not None
    assert window.home.logo_label.pixmap() is not None
    assert not window.home.logo_label.pixmap().isNull()
    assert not window.home.delete_button.isEnabled()
    assert window.log_dock.windowTitle() == "Backend Log"
    assert not window.log_dock.isVisible()
    window.center_on_active_screen()
    screen_center = window.screen().availableGeometry().center()
    frame_center = window.frameGeometry().center()
    assert abs(frame_center.x() - screen_center.x()) <= 2
    assert abs(frame_center.y() - screen_center.y()) <= 2


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
    page.recent_list.addItem(project_path.name)
    item = page.recent_list.item(0)
    item.setData(Qt.ItemDataRole.UserRole, str(project_path))
    page.recent_list.setCurrentItem(item)
    assert page.delete_button.isEnabled()

    deleted = []
    monkeypatch.setattr("e2dm2.ui.QMessageBox.warning", lambda *_args, **_kwargs: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr("e2dm2.ui.delete_project", lambda path: deleted.append(path))
    page.delete_selected_project()
    assert deleted == [project_path]


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


def test_cut_table_and_waveform_selection_stay_synchronized(qtbot):
    dialog = SongEditorDialog(AlphaEntitlementProvider())
    qtbot.addWidget(dialog)
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
