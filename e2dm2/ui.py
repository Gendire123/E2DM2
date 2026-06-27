from __future__ import annotations

import logging
import shutil
from pathlib import Path

from PySide6.QtCore import QObject, QSize, QThread, QTimer, Qt, QUrl, Signal, Slot
from PySide6.QtGui import QCloseEvent, QCursor, QDesktopServices, QGuiApplication, QShowEvent
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDockWidget,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSplitter,
    QStackedWidget,
    QStyle,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .catalog import FULL_LENGTH_TRACKS, default_project_root, filter_songs, load_song_catalog
from .editor import SongEditorDialog
from .entitlements import AlphaEntitlementProvider
from .media import VIDEO_EXTENSIONS
from .models import CancellationToken, ExportSize, ProgressEvent, Project, RenderRequest, WorkflowMode
from .project import create_project, import_media, load_project, move_media, recent_projects, remove_media, save_project
from .render import create_render_plan, render
from .logging_setup import log_file_path


LOGGER = logging.getLogger(__name__)


def _duration(value: float) -> str:
    minutes = int(value // 60)
    return f"{minutes}:{value - minutes * 60:05.2f}"


class CompactPageStack(QStackedWidget):
    def sizeHint(self) -> QSize:
        return QSize(820, 540)

    def minimumSizeHint(self) -> QSize:
        return QSize(640, 340)

    def setCurrentWidget(self, widget: QWidget) -> None:
        super().setCurrentWidget(widget)
        self.updateGeometry()


class NewProjectDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("New E2DM2 Project")
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Project name")
        self.root_edit = QLineEdit(str(default_project_root()))
        browse = QToolButton()
        browse.setText("...")
        browse.setToolTip("Choose project location")
        browse.clicked.connect(self.choose_root)
        root_row = QWidget()
        root_layout = QHBoxLayout(root_row)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.addWidget(self.root_edit)
        root_layout.addWidget(browse)
        form = QFormLayout()
        form.addRow("Name", self.name_edit)
        form.addRow("Location", root_row)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setDefault(True)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def choose_root(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, "Choose project location", self.root_edit.text())
        if selected:
            self.root_edit.setText(selected)

    def accept(self) -> None:
        if not self.name_edit.text().strip():
            QMessageBox.warning(self, "Project name", "Enter a project name.")
            return
        super().accept()


class ImportWorker(QObject):
    progress = Signal(float, str)
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, project: Project, paths: list[Path], cancellation: CancellationToken) -> None:
        super().__init__()
        self.project = project
        self.paths = paths
        self.cancellation = cancellation

    @Slot()
    def run(self) -> None:
        try:
            LOGGER.info("Background import worker started")
            imported = import_media(
                self.project.path,
                self.project.settings,
                self.paths,
                lambda done, total, name: self.progress.emit(done / max(total, 1) * 100, name),
                self.cancellation,
            )
            self.finished.emit(imported)
        except Exception as exc:
            LOGGER.exception("Background import worker failed")
            self.failed.emit(str(exc))


class RenderWorker(QObject):
    progress = Signal(object)
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, project: Project, request: RenderRequest, cancellation: CancellationToken) -> None:
        super().__init__()
        self.project = project
        self.request = request
        self.cancellation = cancellation

    @Slot()
    def run(self) -> None:
        try:
            LOGGER.info("Background render worker started")
            self.progress.emit(ProgressEvent("planning", "Validating media and selecting an encoder", percent=0))
            plan = create_render_plan(self.project, self.request)
            result = render(plan, self.progress.emit, self.cancellation)
            self.finished.emit(result)
        except Exception as exc:
            LOGGER.exception("Background render worker failed")
            self.failed.emit(str(exc))


class BackendLogWidget(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.path = log_file_path()
        self.offset = 0
        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        self.output.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.output.setObjectName("backendLog")
        open_folder = QPushButton("Open Log Folder")
        open_folder.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.path.parent))))
        clear_view = QPushButton("Clear View")
        clear_view.clicked.connect(self.clear_view)
        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel(str(self.path)), 1)
        toolbar.addWidget(open_folder)
        toolbar.addWidget(clear_view)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.addLayout(toolbar)
        layout.addWidget(self.output)
        self.timer = QTimer(self)
        self.timer.setInterval(500)
        self.timer.timeout.connect(self.refresh)
        self.timer.start()
        self.refresh()

    def refresh(self) -> None:
        if not self.path.exists():
            return
        try:
            size = self.path.stat().st_size
            if size < self.offset:
                self.offset = 0
                self.output.clear()
            with self.path.open("r", encoding="utf-8", errors="replace") as handle:
                handle.seek(self.offset)
                text = handle.read()
                self.offset = handle.tell()
            if text:
                self.output.moveCursor(self.output.textCursor().MoveOperation.End)
                self.output.insertPlainText(text)
                self.output.moveCursor(self.output.textCursor().MoveOperation.End)
        except OSError:
            return

    def clear_view(self) -> None:
        self.output.clear()
        self.offset = self.path.stat().st_size if self.path.exists() else 0


class HomePage(QWidget):
    new_requested = Signal()
    open_requested = Signal()
    recent_requested = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        title = QLabel("Easy Epic Drone Movie Maker")
        title.setObjectName("appTitle")
        short_name = QLabel("E2DM2")
        short_name.setObjectName("shortName")
        new_button = QPushButton("New Project")
        open_button = QPushButton("Open Project")
        new_button.clicked.connect(self.new_requested)
        open_button.clicked.connect(self.open_requested)
        actions = QHBoxLayout()
        actions.addWidget(new_button)
        actions.addWidget(open_button)
        actions.addStretch()
        self.recent_list = QListWidget()
        self.recent_list.itemDoubleClicked.connect(lambda item: self.recent_requested.emit(item.data(Qt.ItemDataRole.UserRole)))
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.addWidget(title)
        layout.addWidget(short_name)
        layout.addSpacing(18)
        layout.addLayout(actions)
        layout.addSpacing(24)
        layout.addWidget(QLabel("Recent projects"))
        layout.addWidget(self.recent_list, 1)

    def refresh(self) -> None:
        self.recent_list.clear()
        for path in recent_projects():
            self.recent_list.addItem(path.name)
            list_item = self.recent_list.item(self.recent_list.count() - 1)
            list_item.setToolTip(str(path))
            list_item.setData(Qt.ItemDataRole.UserRole, str(path))


class WorkspacePage(QWidget):
    home_requested = Signal()
    operation_idle = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.project: Project | None = None
        self.songs = []
        self.thread: QThread | None = None
        self.worker: QObject | None = None
        self.cancellation: CancellationToken | None = None
        self.entitlement = AlphaEntitlementProvider()
        self._build_ui()
        self.refresh_catalog()

    def _tool_button(self, icon: QStyle.StandardPixmap, tooltip: str, handler) -> QToolButton:
        button = QToolButton()
        button.setIcon(self.style().standardIcon(icon))
        button.setToolTip(tooltip)
        button.clicked.connect(handler)
        return button

    def _build_ui(self) -> None:
        self.back_button = self._tool_button(QStyle.StandardPixmap.SP_ArrowBack, "Back to projects", self.home_requested.emit)
        self.project_title = QLabel("Project")
        self.project_title.setObjectName("projectTitle")
        self.project_path = QLabel()
        self.project_path.setObjectName("mutedLabel")
        header = QHBoxLayout()
        header.addWidget(self.back_button)
        header.addWidget(self.project_title)
        header.addWidget(self.project_path, 1)

        self.media_table = QTableWidget(0, 6)
        self.media_table.setHorizontalHeaderLabels(["Clip", "Duration", "Resolution", "FPS", "Codec", "Size"])
        self.media_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.media_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.media_table.setSortingEnabled(False)
        header_view = self.media_table.horizontalHeader()
        header_view.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in range(1, 6):
            header_view.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        add_files = QPushButton("Add Files")
        add_folder = QPushButton("Add Folder")
        add_files.clicked.connect(self.add_files)
        add_folder.clicked.connect(self.add_folder)
        up = self._tool_button(QStyle.StandardPixmap.SP_ArrowUp, "Move selected clip up", lambda: self.move_selected(-1))
        down = self._tool_button(QStyle.StandardPixmap.SP_ArrowDown, "Move selected clip down", lambda: self.move_selected(1))
        remove = self._tool_button(QStyle.StandardPixmap.SP_TrashIcon, "Remove selected clip", self.remove_selected)
        media_actions = QHBoxLayout()
        media_actions.addWidget(add_files)
        media_actions.addWidget(add_folder)
        media_actions.addWidget(up)
        media_actions.addWidget(down)
        media_actions.addWidget(remove)
        media_actions.addStretch()
        self.media_total = QLabel("No footage imported")
        media_actions.addWidget(self.media_total)
        media_panel = QWidget()
        media_layout = QVBoxLayout(media_panel)
        media_layout.setContentsMargins(16, 16, 16, 16)
        media_layout.setSpacing(12)
        media_layout.addWidget(QLabel("Footage"))
        media_layout.addWidget(self.media_table)
        media_layout.addLayout(media_actions)

        self.workflow_combo = QComboBox()
        self.workflow_combo.addItem("Epic Montage", WorkflowMode.EPIC_MONTAGE)
        self.workflow_combo.addItem("Full-length Video", WorkflowMode.FULL_LENGTH)
        self.workflow_combo.currentIndexChanged.connect(self.workflow_changed)
        workflow_row = QHBoxLayout()
        workflow_row.addWidget(QLabel("Workflow"))
        workflow_row.addWidget(self.workflow_combo, 1)

        self.epic_panel = self._epic_panel()
        self.full_panel = self._full_panel()
        self.mode_stack = QStackedWidget()
        self.mode_stack.addWidget(self.epic_panel)
        self.mode_stack.addWidget(self.full_panel)

        music_panel = QWidget()
        music_layout = QVBoxLayout(music_panel)
        music_layout.setContentsMargins(16, 16, 16, 16)
        music_layout.setSpacing(12)
        music_layout.addLayout(workflow_row)
        music_layout.addWidget(self.mode_stack, 1)

        music_scroll = QScrollArea()
        music_scroll.setWidgetResizable(True)
        music_scroll.setWidget(music_panel)

        self.source_export = QCheckBox("Source resolution")
        self.hd_export = QCheckBox("1080p maximum")
        self.source_export.setChecked(True)
        export_row = QHBoxLayout()
        export_row.addWidget(QLabel("Exports"))
        export_row.addWidget(self.source_export)
        export_row.addWidget(self.hd_export)
        export_row.addStretch()
        self.render_button = QPushButton("Produce")
        self.render_button.setObjectName("primaryButton")
        self.render_button.clicked.connect(self.start_render)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self.cancel_operation)
        render_actions = QHBoxLayout()
        render_actions.addLayout(export_row, 1)
        render_actions.addWidget(self.render_button)
        render_actions.addWidget(self.cancel_button)

        self.status_label = QLabel("Ready")
        self.status_label.setWordWrap(True)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.results_list = QListWidget()
        self.results_list.itemDoubleClicked.connect(self.open_result)
        self.results_list.setVisible(False)
        open_folder = QPushButton("Open Renders Folder")
        open_folder.clicked.connect(self.open_renders_folder)
        status_panel = QWidget()
        status_layout = QVBoxLayout(status_panel)
        status_layout.setContentsMargins(0, 0, 0, 0)
        status_layout.addWidget(QLabel("Production"))
        status_layout.addWidget(self.status_label)
        status_layout.addWidget(self.progress_bar)
        status_layout.addWidget(self.results_list, 1)
        status_layout.addWidget(open_folder)

        produce_panel = QWidget()
        produce_layout = QVBoxLayout(produce_panel)
        produce_layout.setContentsMargins(16, 16, 16, 16)
        produce_layout.setSpacing(12)
        produce_layout.addLayout(render_actions)
        produce_layout.addWidget(status_panel, 1)
        produce_scroll = QScrollArea()
        produce_scroll.setWidgetResizable(True)
        produce_scroll.setWidget(produce_panel)

        self.workspace_tabs = QTabWidget()
        self.workspace_tabs.addTab(media_panel, "Footage")
        self.workspace_tabs.addTab(music_scroll, "Music")
        self.workspace_tabs.addTab(produce_scroll, "Produce")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 18, 24, 24)
        layout.addLayout(header)
        layout.addWidget(self.workspace_tabs, 1)

    def _epic_panel(self) -> QWidget:
        panel = QWidget()
        self.song_search = QLineEdit()
        self.song_search.setPlaceholderText("Search songs, artists, or moods")
        self.song_search.textChanged.connect(self.apply_song_filters)
        self.mood_filter = QComboBox()
        self.energy_filter = QComboBox()
        self.mood_filter.currentIndexChanged.connect(self.apply_song_filters)
        self.energy_filter.addItems(["All energies", "Low", "Medium", "High"])
        self.energy_filter.currentIndexChanged.connect(self.apply_song_filters)
        manage = QPushButton("Manage Library")
        manage.clicked.connect(self.open_library)
        filters = QHBoxLayout()
        filters.addWidget(self.song_search, 1)
        filters.addWidget(self.mood_filter)
        filters.addWidget(self.energy_filter)
        filters.addWidget(manage)
        self.song_table = QTableWidget(0, 4)
        self.song_table.setHorizontalHeaderLabels(["Song", "Mood", "Cuts", "Length"])
        self.song_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.song_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.song_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.song_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in range(1, 4):
            self.song_table.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        self.song_table.itemSelectionChanged.connect(self.song_selected)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 8, 0, 8)
        layout.addLayout(filters)
        layout.addWidget(self.song_table)
        return panel

    def _full_panel(self) -> QWidget:
        panel = QWidget()
        self.track_combo = QComboBox()
        layout = QFormLayout(panel)
        layout.setContentsMargins(0, 18, 0, 8)
        layout.addRow("Soundtrack", self.track_combo)
        return panel

    def set_project(self, project: Project) -> None:
        self.project = project
        self.project_title.setText(project.settings.name)
        self.project_path.setText(str(project.path))
        workflow_index = self.workflow_combo.findData(project.settings.workflow)
        self.workflow_combo.setCurrentIndex(max(0, workflow_index))
        track_index = self.track_combo.findData(project.settings.full_length_track_id)
        self.track_combo.setCurrentIndex(max(0, track_index))
        self.source_export.setChecked(ExportSize.SOURCE in project.settings.exports)
        self.hd_export.setChecked(ExportSize.HD_1080 in project.settings.exports)
        self.refresh_media()
        self.refresh_catalog(project.settings.song_id)
        self.workflow_changed()
        self.results_list.clear()
        self.results_list.setVisible(False)
        self.status_label.setText("Ready")
        self.progress_bar.setValue(0)
        self.workspace_tabs.setCurrentIndex(0)

    def refresh_media(self) -> None:
        if not self.project:
            return
        media = self.project.settings.media
        self.media_table.setRowCount(len(media))
        for row, item in enumerate(media):
            values = [
                item.original_name, _duration(item.duration), f"{item.width} x {item.height}",
                f"{item.fps:.2f}", item.codec, f"{item.size_bytes / 1024 ** 2:.1f} MB",
            ]
            for column, value in enumerate(values):
                self.media_table.setItem(row, column, QTableWidgetItem(value))
        total_duration = sum(item.duration for item in media)
        total_size = sum(item.size_bytes for item in media)
        self.media_total.setText(f"{len(media)} clips | {_duration(total_duration)} | {total_size / 1024 ** 3:.2f} GB")

    def refresh_catalog(self, selected_id: str | None = None) -> None:
        try:
            self.songs = load_song_catalog()
        except ValueError as exc:
            self.songs = []
            QMessageBox.critical(self, "Epic library error", str(exc))
            
        if hasattr(self, "track_combo"):
            current_track_id = self.track_combo.currentData()
            self.track_combo.blockSignals(True)
            self.track_combo.clear()
            for track in FULL_LENGTH_TRACKS:
                self.track_combo.addItem(f"{track.title} - {track.description}", track.track_id)
            full_length_presets = [s for s in self.songs if s.workflow == WorkflowMode.FULL_LENGTH]
            for song in full_length_presets:
                self.track_combo.addItem(f"{song.title} - {song.artist}", song.song_id)
            index = self.track_combo.findData(current_track_id)
            self.track_combo.setCurrentIndex(max(0, index))
            self.track_combo.blockSignals(False)

        moods = sorted({mood for song in self.songs if song.workflow == WorkflowMode.EPIC_MONTAGE for mood in song.moods}, key=str.casefold)
        current_mood = self.mood_filter.currentText() if hasattr(self, "mood_filter") else "All moods"
        if hasattr(self, "mood_filter"):
            self.mood_filter.blockSignals(True)
            self.mood_filter.clear()
            self.mood_filter.addItem("All moods", "")
            for mood in moods:
                self.mood_filter.addItem(mood.title(), mood)
            index = self.mood_filter.findText(current_mood)
            self.mood_filter.setCurrentIndex(max(0, index))
            self.mood_filter.blockSignals(False)
            self.apply_song_filters(selected_id)

    def apply_song_filters(self, selected_id: str | None = None) -> None:
        if isinstance(selected_id, int):
            selected_id = None
        mood = self.mood_filter.currentData() or ""
        energy = "" if self.energy_filter.currentIndex() == 0 else self.energy_filter.currentText().lower()
        montage_songs = [s for s in self.songs if s.workflow == WorkflowMode.EPIC_MONTAGE]
        filtered = filter_songs(montage_songs, self.song_search.text(), mood, energy)
        current_id = selected_id or (self.project.settings.song_id if self.project else None)
        self.song_table.setRowCount(len(filtered))
        selected_row = -1
        for row, song in enumerate(filtered):
            values = [song.title, ", ".join(song.moods), str(len(song.cut_timestamps)), _duration(song.total_duration_seconds)]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column == 0:
                    item.setData(Qt.ItemDataRole.UserRole, song.song_id)
                    item.setToolTip(f"{song.artist}\nMinimum footage: {_duration(song.minimum_source_duration_seconds)}")
                self.song_table.setItem(row, column, item)
            if song.song_id == current_id:
                selected_row = row
        if selected_row < 0 and filtered:
            selected_row = 0
        if selected_row >= 0:
            self.song_table.selectRow(selected_row)

    def song_selected(self) -> None:
        if not self.project:
            return
        row = self.song_table.currentRow()
        item = self.song_table.item(row, 0) if row >= 0 else None
        if item:
            self.project.settings.song_id = item.data(Qt.ItemDataRole.UserRole)

    def workflow_changed(self) -> None:
        workflow = self.workflow_combo.currentData()
        self.mode_stack.setCurrentIndex(0 if workflow == WorkflowMode.EPIC_MONTAGE else 1)

    def add_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "Import drone footage", "", "Video (*.mp4 *.mov *.m4v)")
        if paths:
            self.start_import([Path(path) for path in paths])

    def add_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Import drone footage folder")
        if folder:
            paths = sorted((path for path in Path(folder).rglob("*") if path.suffix.lower() in VIDEO_EXTENSIONS), key=lambda path: path.name.casefold())
            if paths:
                self.start_import(paths)
            else:
                QMessageBox.information(self, "No footage", "No supported video files were found in that folder.")

    def start_import(self, paths: list[Path]) -> None:
        if not self.project or self.thread:
            return
        self.cancellation = CancellationToken()
        worker = ImportWorker(self.project, paths, self.cancellation)
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(self.import_progress)
        worker.finished.connect(self.import_finished)
        worker.failed.connect(self.operation_failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        worker.failed.connect(worker.deleteLater)
        thread.finished.connect(self.thread_finished)
        self.thread = thread
        self.worker = worker
        self._set_busy(True)
        self.status_label.setText("Copying footage into the project")
        LOGGER.info("UI started import for %d selected file(s)", len(paths))
        thread.start()

    def import_progress(self, percent: float, name: str) -> None:
        self.progress_bar.setValue(round(percent))
        self.status_label.setText(f"Importing {name}")

    def import_finished(self, imported) -> None:
        self.refresh_media()
        self.status_label.setText(f"Imported {len(imported)} clip(s)")
        self.progress_bar.setValue(100)
        LOGGER.info("UI import completed with %d file(s)", len(imported))

    def selected_media_row(self) -> int:
        return self.media_table.currentRow()

    def move_selected(self, direction: int) -> None:
        if not self.project:
            return
        row = self.selected_media_row()
        new_row = row + direction
        if row < 0 or not 0 <= new_row < len(self.project.settings.media):
            return
        move_media(self.project.settings, row, new_row)
        save_project(self.project.path, self.project.settings)
        self.refresh_media()
        self.media_table.selectRow(new_row)

    def remove_selected(self) -> None:
        if not self.project:
            return
        row = self.selected_media_row()
        if row < 0:
            return
        item = self.project.settings.media[row]
        if QMessageBox.question(self, "Remove clip", f"Remove {item.original_name} from this project?") != QMessageBox.StandardButton.Yes:
            return
        removed = remove_media(self.project.settings, row)
        copied_path = removed.resolve(self.project.path)
        source_root = (self.project.path / "source").resolve()
        try:
            copied_path.resolve().relative_to(source_root)
            copied_path.unlink(missing_ok=True)
        except ValueError:
            pass
        save_project(self.project.path, self.project.settings)
        self.refresh_media()

    def open_library(self) -> None:
        dialog = SongEditorDialog(self.entitlement, self)
        dialog.catalog_changed.connect(lambda: self.refresh_catalog(self.project.settings.song_id if self.project else None))
        dialog.exec()
        self.refresh_catalog(self.project.settings.song_id if self.project else None)

    def selected_exports(self) -> list[ExportSize]:
        exports = []
        if self.source_export.isChecked():
            exports.append(ExportSize.SOURCE)
        if self.hd_export.isChecked():
            exports.append(ExportSize.HD_1080)
        return exports

    def start_render(self) -> None:
        LOGGER.info("Produce clicked")
        self.workspace_tabs.setCurrentIndex(2)
        try:
            self._start_render()
        except Exception as exc:
            LOGGER.exception("Production could not start")
            self.operation_failed(str(exc))

    def _start_render(self) -> None:
        if not self.project or self.thread:
            return
        exports = self.selected_exports()
        if not exports:
            QMessageBox.warning(self, "Export size", "Choose at least one export size.")
            return
        workflow = WorkflowMode(self.workflow_combo.currentData())
        song_id = self.project.settings.song_id
        if workflow == WorkflowMode.EPIC_MONTAGE and not song_id:
            QMessageBox.warning(self, "Epic song", "Choose an Epic song.")
            return
        self.project.settings.workflow = workflow
        self.project.settings.full_length_track_id = self.track_combo.currentData()
        self.project.settings.exports = exports
        save_project(self.project.path, self.project.settings)
        request = RenderRequest(workflow, exports, song_id, self.track_combo.currentData())
        self.cancellation = CancellationToken()
        worker = RenderWorker(self.project, request, self.cancellation)
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(self.render_progress)
        worker.finished.connect(self.render_finished)
        worker.failed.connect(self.operation_failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        worker.failed.connect(worker.deleteLater)
        thread.finished.connect(self.thread_finished)
        self.thread = thread
        self.worker = worker
        self.results_list.clear()
        self.results_list.setVisible(False)
        self._set_busy(True)
        LOGGER.info("UI started production")
        thread.start()

    def render_progress(self, event: ProgressEvent) -> None:
        self.status_label.setText(event.message)
        if event.percent is not None:
            self.progress_bar.setValue(round(event.percent))

    def render_finished(self, result) -> None:
        self.results_list.clear()
        for output in result.outputs:
            label = Path(output.output_path).name if output.success else f"Failed: {output.output_id}"
            self.results_list.addItem(label)
            item = self.results_list.item(self.results_list.count() - 1)
            item.setData(Qt.ItemDataRole.UserRole, output.output_path if output.success else "")
            item.setToolTip(output.output_path if output.success else (output.error or "Render failed"))
        if result.outputs:
            self.results_list.setVisible(True)
        if result.cancelled:
            self.status_label.setText("Production cancelled. Completed outputs were kept.")
        elif result.successful_outputs:
            self.status_label.setText(f"Production complete: {len(result.successful_outputs)} output(s)")
            self.progress_bar.setValue(100)
        else:
            self.status_label.setText("Production failed. Open a failed result for details.")

    def operation_failed(self, message: str) -> None:
        self.status_label.setText(message)
        LOGGER.error("UI operation failed: %s", message)
        QMessageBox.critical(self, "Operation failed", message)

    def cancel_operation(self) -> None:
        if self.cancellation:
            self.cancellation.cancel()
            self.status_label.setText("Cancelling...")

    def thread_finished(self) -> None:
        if self.thread:
            self.thread.deleteLater()
        self.thread = None
        self.worker = None
        self.cancellation = None
        self._set_busy(False)
        self.operation_idle.emit()

    def _set_busy(self, busy: bool) -> None:
        self.back_button.setEnabled(not busy)
        self.render_button.setEnabled(not busy)
        self.cancel_button.setEnabled(busy)
        self.media_table.setEnabled(not busy)
        self.workflow_combo.setEnabled(not busy)

    def open_result(self, item) -> None:
        path = item.data(Qt.ItemDataRole.UserRole)
        if path:
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))
        else:
            QMessageBox.warning(self, "Render failed", item.toolTip())

    def open_renders_folder(self) -> None:
        if self.project:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.project.path / "renders")))


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Easy Epic Drone Movie Maker - E2DM2")
        self.resize(820, 540)
        self._centered_once = False
        self.stack = CompactPageStack()
        self.home = HomePage()
        self.workspace = WorkspacePage()
        self.stack.addWidget(self.home)
        self.stack.addWidget(self.workspace)
        self.setCentralWidget(self.stack)
        self.log_dock = QDockWidget("Backend Log", self)
        self.log_dock.setObjectName("backendLogDock")
        self.log_dock.setWidget(BackendLogWidget())
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.log_dock)
        self.resizeDocks([self.log_dock], [120], Qt.Orientation.Vertical)
        self.log_dock.hide()
        self.menuBar().addMenu("View").addAction(self.log_dock.toggleViewAction())
        self.home.new_requested.connect(self.new_project)
        self.home.open_requested.connect(self.open_project)
        self.home.recent_requested.connect(lambda path: self.load_project_path(Path(path)))
        self.workspace.home_requested.connect(self.show_home)
        LOGGER.info("E2DM2 main window initialized")
        self.show_home()

    def show_home(self) -> None:
        self.home.refresh()
        self.stack.setCurrentWidget(self.home)

    def new_project(self) -> None:
        dialog = NewProjectDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            project = create_project(dialog.name_edit.text().strip(), Path(dialog.root_edit.text()))
            self.workspace.set_project(project)
            self.stack.setCurrentWidget(self.workspace)
        except OSError as exc:
            LOGGER.exception("Could not create project")
            QMessageBox.critical(self, "Could not create project", str(exc))

    def open_project(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Open E2DM2 Project", str(default_project_root()), "E2DM2 Project (project.json)")
        if path:
            self.load_project_path(Path(path))

    def load_project_path(self, path: Path) -> None:
        try:
            project = load_project(path)
            self.workspace.set_project(project)
            self.stack.setCurrentWidget(self.workspace)
        except (OSError, ValueError, KeyError) as exc:
            LOGGER.exception("Could not open project: %s", path)
            QMessageBox.critical(self, "Could not open project", str(exc))

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.workspace.thread:
            QMessageBox.information(
                self,
                "Operation in progress",
                "Cancel the active import or render and wait for it to finish before closing E2DM2.",
            )
            event.ignore()
            return
        event.accept()

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        if not self._centered_once:
            self._centered_once = True
            QTimer.singleShot(0, self.center_on_active_screen)

    def center_on_active_screen(self) -> None:
        screen = QGuiApplication.screenAt(QCursor.pos()) or self.screen() or QApplication.primaryScreen()
        if not screen:
            return
        frame = self.frameGeometry()
        frame.moveCenter(screen.availableGeometry().center())
        self.move(frame.topLeft())


STYLESHEET = """
QWidget { background: #f4f5f2; color: #202521; font-size: 10pt; }
QMainWindow, QDialog { background: #f4f5f2; }
QLabel#appTitle { font-size: 25pt; font-weight: 650; color: #18342a; }
QLabel#shortName { font-size: 13pt; color: #9a5b16; }
QLabel#projectTitle { font-size: 17pt; font-weight: 650; color: #18342a; }
QLabel#mutedLabel { color: #68716b; }
QLineEdit, QComboBox, QTableWidget, QListWidget, QDoubleSpinBox {
    background: #ffffff; border: 1px solid #c8cec9; border-radius: 4px; padding: 5px;
}
QAbstractItemView { background-color: #ffffff; alternate-background-color: #f7f8f6; }
QTableWidget { gridline-color: #e0e4e0; }
QHeaderView::section { background: #e7ebe7; color: #354039; border: 0; border-bottom: 1px solid #c8cec9; padding: 7px; }
QPushButton, QToolButton { background: #ffffff; border: 1px solid #b8c0ba; border-radius: 5px; padding: 7px 12px; }
QPushButton:hover, QToolButton:hover { background: #edf1ed; border-color: #789080; }
QPushButton:disabled, QToolButton:disabled { color: #99a19b; background: #eceeec; }
QPushButton#primaryButton { background: #246447; color: white; border-color: #246447; font-weight: 600; }
QPushButton#primaryButton:hover { background: #1c543a; }
QProgressBar { background: #e0e4e0; border: 0; border-radius: 4px; height: 16px; text-align: center; }
QProgressBar::chunk { background: #d08a2f; border-radius: 4px; }
QPlainTextEdit#backendLog { background: #171b18; color: #dce6df; border: 1px solid #39433c; font-family: Consolas; font-size: 9pt; }
QTabWidget::pane { border: 1px solid #c8cec9; background: #ffffff; }
QTabBar::tab { background: #e7ebe7; padding: 8px 16px; }
QTabBar::tab:selected { background: #ffffff; color: #246447; }
QSplitter::handle { background: #d7dcd8; width: 1px; }
"""


def create_application() -> QApplication:
    application = QApplication.instance() or QApplication([])
    application.setApplicationName("E2DM2")
    application.setOrganizationName("E2DM2")
    application.setStyle("Fusion")
    application.setStyleSheet(STYLESHEET)
    return application
