import os
import subprocess

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, Qt, Signal, Slot

from e2dm2.models import RenderResult, WorkflowMode
from e2dm2.editor import SongEditorDialog
from e2dm2.entitlements import AlphaEntitlementProvider
from e2dm2.ui import MainWindow
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

