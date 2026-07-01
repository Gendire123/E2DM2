from __future__ import annotations

import json
import logging
import os
import sys
import urllib.request
import tempfile
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal, Slot, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QMessageBox,
    QTextBrowser,
    QWidget,
)

LOGGER = logging.getLogger(__name__)

def parse_version(v_str: str) -> tuple[int, ...]:
    """Parse semver string into a tuple of integers for comparison."""
    try:
        # Strip v-prefix and non-numeric suffixes if any (like -alpha)
        clean = v_str.lstrip("v").split("-")[0]
        return tuple(int(x) for x in clean.split("."))
    except Exception:
        return (0,)


class CheckUpdateThread(QThread):
    finished = Signal(dict)
    error = Signal(str)

    def __init__(self, repo_owner: str, repo_name: str, parent: QObject | None = None):
        super().__init__(parent)
        self.repo_owner = repo_owner
        self.repo_name = repo_name

    def run(self):
        try:
            url = f"https://api.github.com/repos/{self.repo_owner}/{self.repo_name}/releases/latest"
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "E2DM2-Updater",
                    "Accept": "application/vnd.github.v3+json",
                }
            )
            # Fetch release details from GitHub API
            with urllib.request.urlopen(req, timeout=10) as response:
                data = json.loads(response.read().decode("utf-8"))
                tag_name = data.get("tag_name", "").strip()
                version = tag_name.lstrip("v")
                body = data.get("body", "")

                download_url = None
                for asset in data.get("assets", []):
                    name = asset.get("name", "")
                    if name.endswith(".exe"):
                        download_url = asset.get("browser_download_url")
                        break

                self.finished.emit({
                    "version": version,
                    "download_url": download_url,
                    "body": body,
                })
        except Exception as e:
            LOGGER.error(f"Error checking updates from GitHub: {e}")
            self.error.emit(str(e))


class UpdateDownloadThread(QThread):
    progress_changed = Signal(int, int)  # downloaded, total
    finished = Signal(str)               # destination path
    error = Signal(str)

    def __init__(self, download_url: str, dest_path: str, parent: QObject | None = None):
        super().__init__(parent)
        self.download_url = download_url
        self.dest_path = dest_path
        self._is_cancelled = False

    def cancel(self):
        self._is_cancelled = True

    def run(self):
        try:
            req = urllib.request.Request(
                self.download_url,
                headers={"User-Agent": "E2DM2-Updater"}
            )
            with urllib.request.urlopen(req, timeout=30) as response:
                total_size = int(response.info().get("Content-Length", 0))
                bytes_downloaded = 0
                block_size = 16384
                with open(self.dest_path, "wb") as f:
                    while not self._is_cancelled:
                        buffer = response.read(block_size)
                        if not buffer:
                            break
                        f.write(buffer)
                        bytes_downloaded += len(buffer)
                        self.progress_changed.emit(bytes_downloaded, total_size)
                
                if self._is_cancelled:
                    try:
                        os.remove(self.dest_path)
                    except OSError:
                        pass
                    self.error.emit("Download cancelled.")
                else:
                    self.finished.emit(self.dest_path)
        except Exception as e:
            LOGGER.error(f"Error downloading update: {e}")
            self.error.emit(str(e))


class UpdateProgressDialog(QDialog):
    def __init__(self, download_url: str, version: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.download_url = download_url
        self.version = version
        
        self.setWindowTitle("Downloading Update")
        self.setModal(True)
        self.setMinimumWidth(400)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        self.label = QLabel(f"Downloading E2DM2 Setup {version}...")
        self.label.setStyleSheet("font-weight: bold; color: #142033;")
        layout.addWidget(self.label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                border: 1px solid #E1E8EA;
                border-radius: 4px;
                text-align: center;
                background: #FFFFFF;
                color: #142033;
                font-weight: bold;
            }
            QProgressBar::chunk {
                background-color: #0E56AA;
                border-radius: 3px;
            }
        """)
        layout.addWidget(self.progress_bar)

        self.status_label = QLabel("0 MB / 0 MB")
        self.status_label.setStyleSheet("color: #526173; font-size: 9.5pt;")
        layout.addWidget(self.status_label)

        buttons_layout = QHBoxLayout()
        buttons_layout.addStretch()
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setStyleSheet("""
            QPushButton {
                background: #FFFFFF;
                border: 1px solid #C4D1D5;
                border-radius: 6px;
                padding: 6px 14px;
                color: #142033;
            }
            QPushButton:hover {
                background: #F5F7F8;
            }
        """)
        self.cancel_button.clicked.connect(self.reject)
        buttons_layout.addWidget(self.cancel_button)
        layout.addLayout(buttons_layout)

        # Temporary file path for setup
        self.temp_dir = tempfile.gettempdir()
        self.dest_path = str(Path(self.temp_dir) / f"E2DM2-Setup-{version}.exe")

        self.download_thread = UpdateDownloadThread(self.download_url, self.dest_path, self)
        self.download_thread.progress_changed.connect(self.on_progress)
        self.download_thread.finished.connect(self.on_finished)
        self.download_thread.error.connect(self.on_error)

    def showEvent(self, event):
        super().showEvent(event)
        self.download_thread.start()

    def reject(self):
        self.download_thread.cancel()
        super().reject()

    def on_progress(self, downloaded: int, total: int):
        if total > 0:
            pct = int((downloaded / total) * 100)
            self.progress_bar.setValue(pct)
            downloaded_mb = downloaded / (1024 * 1024)
            total_mb = total / (1024 * 1024)
            self.status_label.setText(f"{downloaded_mb:.1f} MB / {total_mb:.1f} MB ({pct}%)")
        else:
            self.progress_bar.setRange(0, 0)
            downloaded_mb = downloaded / (1024 * 1024)
            self.status_label.setText(f"{downloaded_mb:.1f} MB downloaded (unknown size)")

    def on_finished(self, filepath: str):
        self.accept()
        # Prompt and execute installer
        msg = QMessageBox(self.parentWidget())
        msg.setWindowTitle("Update Ready")
        msg.setText("The update installer has been downloaded successfully.")
        msg.setInformativeText(
            "To apply the update, E2DM2 will close and start the setup. "
            "If you have previous versions, they will be uninstalled during setup.\n\n"
            "Would you like to install now?"
        )
        msg.setIcon(QMessageBox.Icon.Question)
        msg.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        msg.setDefaultButton(QMessageBox.StandardButton.Yes)
        
        if msg.exec() == QMessageBox.StandardButton.Yes:
            try:
                # Launch the setup installer and quit this app
                os.startfile(filepath)
                sys.exit(0)
            except Exception as e:
                QMessageBox.critical(
                    self.parentWidget(),
                    "Installation Failed",
                    f"Could not launch installer: {e}\n\nYou can manually run it at: {filepath}"
                )

    def on_error(self, err_msg: str):
        self.reject()
        if "cancelled" not in err_msg.lower():
            QMessageBox.critical(
                self.parentWidget(),
                "Download Error",
                f"An error occurred while downloading the update:\n{err_msg}"
            )


class UpdateDialog(QDialog):
    def __init__(self, version: str, notes: str, download_url: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.version = version
        self.download_url = download_url

        self.setWindowTitle("Software Update Available")
        self.setMinimumSize(480, 360)
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        title_label = QLabel(f"A new version of E2DM2 is available: <b>{version}</b>")
        title_label.setStyleSheet("font-size: 11pt; color: #142033;")
        layout.addWidget(title_label)

        notes_label = QLabel("Release Notes:")
        notes_label.setStyleSheet("font-weight: bold; color: #526173;")
        layout.addWidget(notes_label)

        self.browser = QTextBrowser()
        self.browser.setHtml(self.format_release_notes(notes))
        self.browser.setOpenExternalLinks(True)
        self.browser.setStyleSheet("""
            QTextBrowser {
                background: #FFFFFF;
                border: 1px solid #E1E8EA;
                border-radius: 6px;
                padding: 10px;
                color: #142033;
            }
        """)
        layout.addWidget(self.browser)

        buttons_layout = QHBoxLayout()
        
        # Link to view releases on GitHub directly if download url isn't found
        self.github_button = QPushButton("Open in Browser")
        self.github_button.setStyleSheet("""
            QPushButton {
                background: transparent;
                border: 0;
                color: #0E56AA;
                text-decoration: underline;
                font-weight: bold;
            }
        """)
        self.github_button.clicked.connect(self.open_github_page)
        buttons_layout.addWidget(self.github_button)

        buttons_layout.addStretch()

        self.cancel_button = QPushButton("Later")
        self.cancel_button.setStyleSheet("""
            QPushButton {
                background: #FFFFFF;
                border: 1px solid #C4D1D5;
                border-radius: 6px;
                padding: 8px 16px;
                color: #142033;
            }
            QPushButton:hover {
                background: #F5F7F8;
            }
        """)
        self.cancel_button.clicked.connect(self.reject)
        buttons_layout.addWidget(self.cancel_button)

        self.download_button = QPushButton("Download & Install")
        self.download_button.setStyleSheet("""
            QPushButton {
                background: #0E56AA;
                border: 0;
                border-radius: 6px;
                padding: 8px 18px;
                color: #FFFFFF;
                font-weight: bold;
            }
            QPushButton:hover {
                background: #0A4384;
            }
        """)
        self.download_button.clicked.connect(self.accept)
        buttons_layout.addWidget(self.download_button)

        layout.addLayout(buttons_layout)

    def open_github_page(self):
        QDesktopServices.openUrl(QUrl("https://github.com/Gendire123/E2DM2-Releases/releases"))

    def format_release_notes(self, notes: str) -> str:
        # Simple plain text to html conversion
        html = notes.replace("\n", "<br>")
        return f"<span style='font-family: \"Segoe UI\", sans-serif; font-size: 10pt; color: #142033;'>{html}</span>"


class UpdateChecker(QObject):
    def __init__(self, current_version: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.current_version = current_version
        self.parent_widget = parent
        self.check_thread = None
        self.repo_owner = "Gendire123"
        self.repo_name = "E2DM2-Releases"
        self._silent_on_latest = False

    def check(self, silent_on_latest: bool = False):
        """Start the update check process."""
        self._silent_on_latest = silent_on_latest
        self.check_thread = CheckUpdateThread(self.repo_owner, self.repo_name, self)
        self.check_thread.finished.connect(self.on_check_finished)
        self.check_thread.error.connect(self.on_check_error)
        self.check_thread.start()

    @Slot(dict)
    def on_check_finished(self, release_info: dict):
        latest_version = release_info["version"]
        download_url = release_info["download_url"]
        notes = release_info["body"]

        # Parse versions
        cur_v = parse_version(self.current_version)
        lat_v = parse_version(latest_version)

        if lat_v > cur_v:
            # Update available!
            if not download_url:
                # If there's no exe asset in the release, inform user to visit page
                QMessageBox.warning(
                    self.parent_widget,
                    "Update Available",
                    f"A new version ({latest_version}) is available, but the setup package is not hosted on GitHub releases yet.\n\n"
                    "Please visit the website to update."
                )
                return

            dialog = UpdateDialog(latest_version, notes, download_url, self.parent_widget)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                # Start downloading the update
                progress = UpdateProgressDialog(download_url, latest_version, self.parent_widget)
                progress.exec()
        else:
            if not self._silent_on_latest:
                QMessageBox.information(
                    self.parent_widget,
                    "Software Update",
                    f"You are running the latest version of E2DM2 (Version {self.current_version})."
                )

    @Slot(str)
    def on_check_error(self, err_msg: str):
        if not self._silent_on_latest:
            QMessageBox.critical(
                self.parent_widget,
                "Check Update Failed",
                f"Could not check for updates:\n{err_msg}"
            )
