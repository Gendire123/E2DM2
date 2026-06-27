from __future__ import annotations

import shutil
import sys

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QMessageBox

from .logging_setup import configure_logging
from .ui import AppSplashScreen, MainWindow, create_application


def main() -> int:
    configure_logging()
    app = create_application()
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        QMessageBox.critical(None, "FFmpeg required", "FFmpeg and FFprobe must be available through PATH.")
        return 1

    splash = AppSplashScreen()
    splash.show()
    app.processEvents()

    window = MainWindow()

    def start_app() -> None:
        splash.close()
        window.show()

    QTimer.singleShot(3000, start_app)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())

