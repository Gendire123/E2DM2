import os
import subprocess

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, Signal, Slot

from e2dm2.models import RenderResult, WorkflowMode
from e2dm2.ui import MainWindow
from e2dm2.project import create_project
from e2dm2.ui import WorkspacePage


def test_main_window_smoke(qtbot):
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    assert window.windowTitle().startswith("Easy Epic Drone Movie Maker")
    assert window.workspace.song_table.rowCount() >= 2
    assert window.home.recent_list is not None
    assert window.log_dock.windowTitle() == "Backend Log"


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
