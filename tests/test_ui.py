import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from e2dm2.ui import MainWindow


def test_main_window_smoke(qtbot):
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    assert window.windowTitle().startswith("Easy Epic Drone Movie Maker")
    assert window.workspace.song_table.rowCount() >= 2
    assert window.home.recent_list is not None
