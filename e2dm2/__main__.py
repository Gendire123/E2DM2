from __future__ import annotations

import shutil
import sys

from PySide6.QtWidgets import QMessageBox

from .ui import MainWindow, create_application


def main() -> int:
    app = create_application()
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        QMessageBox.critical(None, "FFmpeg required", "FFmpeg and FFprobe must be available through PATH.")
        return 1
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
