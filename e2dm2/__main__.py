from __future__ import annotations

import shutil
import sys

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QMessageBox

from .logging_setup import configure_logging
from .runtime import configure_bundled_tools
from .ui import AppSplashScreen, MainWindow, create_application, splash_screen_enabled


def main() -> int:
    configure_bundled_tools()
    configure_logging()
    app = create_application()
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        QMessageBox.critical(None, "FFmpeg required", "FFmpeg and FFprobe must be available through PATH.")
        return 1

    if splash_screen_enabled():
        splash = AppSplashScreen()
        splash.show()
        app.processEvents()
        window = MainWindow()

        def start_app() -> None:
            splash.close()
            window.show_maximized_on_active_screen()

        QTimer.singleShot(3000, start_app)
    else:
        window = MainWindow()
        window.show_maximized_on_active_screen()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
