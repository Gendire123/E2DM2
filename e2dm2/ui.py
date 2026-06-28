from __future__ import annotations

import logging
import json
import shutil
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import (
    QEasingCurve,
    QPointF,
    QPropertyAnimation,
    QRectF,
    QObject,
    QSize,
    QSettings,
    QThread,
    QTimer,
    Qt,
    QUrl,
    Signal,
    Slot,
)
from PySide6.QtGui import (
    QCloseEvent,
    QColor,
    QCursor,
    QDesktopServices,
    QGuiApplication,
    QIcon,
    QMouseEvent,
    QPainter,
    QPen,
    QPixmap,
    QPolygonF,
    QShowEvent,
)
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDockWidget,
    QFileDialog,
    QFormLayout,
    QFrame,
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
    QSlider,
    QSplitter,
    QStackedWidget,
    QStyle,
    QStyleOptionButton,
    QStyleOptionSlider,
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
from .media import VIDEO_EXTENSIONS, preview_proxy_path
from .models import CancellationToken, ExportSize, ProgressEvent, Project, RenderRequest, WorkflowMode
from .preview import ClipPreviewDialog
from .project import (
    create_project,
    delete_project,
    import_media,
    load_project,
    move_media,
    recent_projects,
    remove_media,
    save_project,
)
from .render import create_render_plan, render
from .logging_setup import log_file_path


LOGGER = logging.getLogger(__name__)
SHOW_SPLASH_SETTING = "startup/show_splash_screen"
APP_ICON_PATH = Path(__file__).parent / "assets" / "icons" / "app-icon.ico"


def splash_screen_enabled(settings: QSettings | None = None) -> bool:
    settings = settings or QSettings()
    return settings.value(SHOW_SPLASH_SETTING, True, type=bool)


def _duration(value: float) -> str:
    minutes = int(value // 60)
    return f"{minutes}:{value - minutes * 60:05.2f}"


def _song_transport_icon(stopping: bool) -> QIcon:
    pixmap = QPixmap(24, 24)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#ffffff"))
    if stopping:
        painter.drawRoundedRect(QRectF(6, 6, 12, 12), 1.5, 1.5)
    else:
        painter.drawPolygon(QPolygonF([QPointF(7, 4), QPointF(19, 12), QPointF(7, 20)]))
    painter.end()
    return QIcon(pixmap)


class ClickSeekSlider(QSlider):
    position_requested = Signal(int)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return

        option = QStyleOptionSlider()
        self.initStyleOption(option)
        handle = self.style().subControlRect(
            QStyle.ComplexControl.CC_Slider,
            option,
            QStyle.SubControl.SC_SliderHandle,
            self,
        )
        if handle.contains(event.position().toPoint()):
            super().mousePressEvent(event)
            return

        if self.orientation() == Qt.Orientation.Horizontal:
            offset = round(event.position().x())
            span = max(1, self.width())
        else:
            offset = round(event.position().y())
            span = max(1, self.height())
        value = QStyle.sliderValueFromPosition(
            self.minimum(), self.maximum(), offset, span, option.upsideDown,
        )
        self.setValue(value)
        self.position_requested.emit(value)
        event.accept()


class SongPreviewCell(QWidget):
    play_requested = Signal()
    seek_requested = Signal(int)

    def __init__(self, title: str, duration_seconds: float, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("songPreviewCell")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._playing = False
        self._selected = False
        self._transport_visible = False
        self._animation_direction: str | None = None
        self._progress_animation = QPropertyAnimation(self)
        self._progress_animation.setTargetObject(None)
        self.title_label = QLabel(title)
        self.play_button = QToolButton()
        self.play_button.setFixedSize(34, 34)
        self.play_button.setIconSize(QSize(24, 24))
        self.play_button.setToolTip("Play")
        self.play_button.setAccessibleName(f"Play {title}")
        self.play_button.setIcon(_song_transport_icon(False))
        self.play_button.clicked.connect(self.play_requested.emit)

        self.progress_slider = ClickSeekSlider(Qt.Orientation.Horizontal)
        self.progress_slider.setRange(0, max(1, round(duration_seconds * 1000)))
        self.progress_slider.setMinimumHeight(26)
        self.progress_slider.setToolTip("Song position")
        self.progress_slider.setVisible(False)
        self.progress_slider.setStyleSheet(
            "QSlider::groove:horizontal { height: 6px; background: #dce5df; border-radius: 3px; }"
            "QSlider::sub-page:horizontal { background: #1870c8; border-radius: 3px; }"
            "QSlider::add-page:horizontal { background: #dce5df; border-radius: 3px; }"
            "QSlider::handle:horizontal { width: 18px; height: 18px; margin: -6px 0; background: #ffffff; "
            "border: 2px solid #0e54a9; border-radius: 9px; }"
        )
        self.progress_slider.sliderMoved.connect(self.seek_requested.emit)
        self.progress_slider.position_requested.connect(self.seek_requested.emit)
        self._progress_animation.setTargetObject(self.progress_slider)
        self._progress_animation.setPropertyName(b"maximumWidth")
        self._progress_animation.setDuration(240)
        self._progress_animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._progress_animation.finished.connect(self._progress_expansion_finished)
        self._progress_animation.valueChanged.connect(lambda _value: self.update())

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(7)
        layout.addWidget(self.title_label)
        layout.addWidget(self.play_button)
        layout.addWidget(self.progress_slider, 1)
        self._apply_colors()

    def set_playing(self, playing: bool, animate: bool = True) -> None:
        was_playing = self._playing
        self._playing = playing
        action = "Stop" if playing else "Play"
        self.play_button.setIcon(_song_transport_icon(playing))
        self.play_button.setToolTip(action)
        self.play_button.setAccessibleName(f"{action} {self.title_label.text()}")
        if playing and not was_playing:
            self._animate_progress_expansion()
        elif not playing and was_playing and animate:
            self._animate_progress_collapse()
        elif not playing:
            self._progress_animation.stop()
            self._animation_direction = None
            self._transport_visible = False
            self.progress_slider.setVisible(False)
            self.progress_slider.setMaximumWidth(16777215)
        self._apply_colors()

    def _animate_progress_expansion(self) -> None:
        self._progress_animation.stop()
        start_width = self.progress_slider.width() if self.progress_slider.isVisible() else 0
        self._transport_visible = True
        self.progress_slider.setMaximumWidth(16777215)
        self.progress_slider.setVisible(True)
        if self.layout() is not None:
            self.layout().activate()
        target_width = max(self.progress_slider.sizeHint().width(), self.progress_slider.width())
        self.progress_slider.setMaximumWidth(start_width)
        if self.layout() is not None:
            self.layout().activate()
        self._animation_direction = "expand"
        self._progress_animation.setStartValue(start_width)
        self._progress_animation.setEndValue(target_width)
        self._progress_animation.start()

    def _animate_progress_collapse(self) -> None:
        self._progress_animation.stop()
        self._transport_visible = True
        self.progress_slider.setVisible(True)
        current_width = self.progress_slider.width()
        self.progress_slider.setMaximumWidth(current_width)
        self._animation_direction = "collapse"
        self._progress_animation.setStartValue(current_width)
        self._progress_animation.setEndValue(0)
        self._progress_animation.start()

    def _progress_expansion_finished(self) -> None:
        direction = self._animation_direction
        self._animation_direction = None
        if direction == "expand" and self._playing:
            self.progress_slider.setMaximumWidth(16777215)
        elif direction == "collapse" and not self._playing:
            self.progress_slider.setVisible(False)
            self.progress_slider.setMaximumWidth(16777215)
            self._transport_visible = False
            if self.layout() is not None:
                self.layout().activate()
            self.update()

    def set_position(self, position: int) -> None:
        if not self.progress_slider.isSliderDown():
            self.progress_slider.setValue(position)

    def set_duration(self, duration: int) -> None:
        if duration > 0:
            self.progress_slider.setMaximum(duration)

    def set_selected(self, selected: bool) -> None:
        self._selected = selected
        self._apply_colors()

    def _apply_colors(self) -> None:
        background = "#0e54a9" if self._selected else "#fcfcfc"
        foreground = "#ffffff" if self._selected else "#18342a"
        button = "#1870c8" if self._playing else "#0e54a9"
        button_hover = "#0d5fae" if self._playing else "#083d7d"
        border = "#f5faf7" if self._selected and not self._playing else "#b9c8c0"
        self.setStyleSheet(f"QWidget#songPreviewCell {{ background: {background}; }}")
        self.title_label.setStyleSheet(f"background: transparent; color: {foreground}; font-weight: 500;")
        self.play_button.setStyleSheet(
            f"QToolButton {{ border: 2px solid {border}; border-radius: 17px; background: {button}; padding: 3px; }}"
            f"QToolButton:hover {{ background: {button_hover}; border-color: #ffffff; }}"
            f"QToolButton:pressed {{ background: {button_hover}; }}"
        )
        self.update()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if self._transport_visible:
            transport_left = max(0, self.play_button.geometry().left() - 5)
            painter = QPainter(self)
            painter.fillRect(transport_left, 0, self.width() - transport_left, self.height(), QColor("#fcfcfc"))
            painter.end()


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


PROJECT_MODIFIED_ROLE = int(Qt.ItemDataRole.UserRole) + 1
PROJECT_SORT_ROLE = int(Qt.ItemDataRole.UserRole) + 2


class ProjectTableItem(QTableWidgetItem):
    def __lt__(self, other: QTableWidgetItem) -> bool:
        left = self.data(PROJECT_SORT_ROLE)
        right = other.data(PROJECT_SORT_ROLE)
        if left is not None and right is not None:
            return left < right
        return super().__lt__(other)


class HomePage(QWidget):
    new_requested = Signal()
    open_requested = Signal()
    recent_requested = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        brand_card = QFrame()
        brand_card.setObjectName("brandCard")
        self.logo_label = QLabel()
        self.logo_label.setObjectName("brandLogo")
        self.logo_label.setFixedSize(300, 200)
        self.logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo = QPixmap(str(Path(__file__).parent / "assets" / "logo.jpg"))
        if logo.isNull():
            self.logo_label.setText("E2DM2")
        else:
            self.logo_label.setPixmap(logo.scaled(
                self.logo_label.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation,
            ))

        self.title_label = QLabel("Create cinematic drone films")
        self.title_label.setObjectName("appTitle")
        self.title_label.setWordWrap(True)
        subtitle = QLabel(
            "Import your footage, guide the edit, and produce a polished music-driven movie, all in one project."
        )
        subtitle.setObjectName("homeSubtitle")
        subtitle.setWordWrap(True)
        new_button = QPushButton("New Project")
        new_button.setObjectName("primaryButton")
        self.open_button = QPushButton("Open Project")
        new_button.clicked.connect(self.new_requested)
        self.open_button.clicked.connect(self.open_preferred_project)
        actions = QHBoxLayout()
        actions.addWidget(new_button)
        actions.addWidget(self.open_button)
        actions.addStretch()

        brand_copy = QVBoxLayout()
        brand_copy.setSpacing(10)
        brand_copy.addStretch()
        brand_copy.addWidget(self.title_label)
        brand_copy.addWidget(subtitle)
        brand_copy.addSpacing(8)
        brand_copy.addLayout(actions)
        brand_copy.addStretch()
        brand_layout = QHBoxLayout(brand_card)
        brand_layout.setContentsMargins(18, 14, 22, 14)
        brand_layout.setSpacing(24)
        brand_layout.addWidget(self.logo_label)
        brand_layout.addLayout(brand_copy, 1)

        self.recent_list = QTableWidget(0, 3)
        self.recent_list.setObjectName("recentProjectsTable")
        self.recent_list.setHorizontalHeaderLabels(["Project title", "Created", "Last modified"])
        self.recent_list.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.recent_list.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.recent_list.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.recent_list.setAlternatingRowColors(True)
        self.recent_list.verticalHeader().setVisible(False)
        self.recent_list.verticalHeader().setDefaultSectionSize(38)
        self.recent_list.setMinimumHeight(self.recent_list.horizontalHeader().sizeHint().height() + 5 * 38 + 4)
        self.recent_list.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.recent_list.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.recent_list.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.recent_list.setSortingEnabled(True)
        self.recent_list.itemDoubleClicked.connect(
            lambda item: self.recent_requested.emit(item.data(Qt.ItemDataRole.UserRole))
        )
        self.recent_list.itemSelectionChanged.connect(self.update_delete_button)
        recent_title = QLabel("Recent projects")
        recent_title.setObjectName("sectionTitle")
        self.delete_button = QPushButton("Delete Selected")
        self.delete_button.setObjectName("destructiveButton")
        self.delete_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_TrashIcon))
        self.delete_button.setEnabled(False)
        self.delete_button.clicked.connect(self.delete_selected_project)
        recent_header = QHBoxLayout()
        recent_header.addWidget(recent_title)
        recent_header.addStretch()
        recent_header.addWidget(self.delete_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 24)
        layout.setSpacing(16)
        layout.addWidget(brand_card)
        layout.addLayout(recent_header)
        layout.addWidget(self.recent_list, 1)

    def refresh(self) -> None:
        paths = recent_projects()
        self.recent_list.setSortingEnabled(False)
        self.recent_list.setRowCount(len(paths))
        for row, path in enumerate(paths):
            project_file = path / "project.json"
            try:
                data = json.loads(project_file.read_text(encoding="utf-8"))
            except (OSError, ValueError, TypeError):
                data = {}
            title = str(data.get("name") or path.name)
            created_at = self._project_datetime(data.get("created_at"), project_file, created=True)
            modified_at = self._project_datetime(data.get("updated_at"), project_file, created=False)
            created = self._format_project_timestamp(created_at)
            modified = self._format_project_timestamp(modified_at)
            for column, value in enumerate((title, created, modified)):
                item = ProjectTableItem(value)
                item.setToolTip(str(path))
                item.setData(Qt.ItemDataRole.UserRole, str(path))
                item.setData(PROJECT_MODIFIED_ROLE, modified_at.timestamp() if modified_at else float("-inf"))
                sort_value = (
                    title.casefold() if column == 0 else
                    created_at.timestamp() if column == 1 and created_at else
                    modified_at.timestamp() if modified_at else float("-inf")
                )
                item.setData(PROJECT_SORT_ROLE, sort_value)
                if column > 0:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.recent_list.setItem(row, column, item)
        self.recent_list.setSortingEnabled(True)
        self.recent_list.sortItems(2, Qt.SortOrder.DescendingOrder)
        self.update_delete_button()

    @staticmethod
    def _project_datetime(value, project_file: Path, *, created: bool) -> datetime | None:
        try:
            timestamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            if timestamp.tzinfo is not None:
                timestamp = timestamp.astimezone()
        except (TypeError, ValueError):
            try:
                file_timestamp = project_file.stat().st_ctime if created else project_file.stat().st_mtime
                timestamp = datetime.fromtimestamp(file_timestamp).astimezone()
            except OSError:
                return None
        return timestamp

    @staticmethod
    def _format_project_timestamp(timestamp: datetime | None) -> str:
        if timestamp is None:
            return "Unavailable"
        return timestamp.strftime("%Y-%m-%d  %H:%M")

    def open_preferred_project(self) -> None:
        selected_items = self.recent_list.selectedItems()
        if selected_items:
            self.recent_requested.emit(selected_items[0].data(Qt.ItemDataRole.UserRole))
            return
        if self.recent_list.rowCount() == 0:
            self.open_requested.emit()
            return
        latest_item = max(
            (self.recent_list.item(row, 0) for row in range(self.recent_list.rowCount())),
            key=lambda item: item.data(PROJECT_MODIFIED_ROLE),
        )
        self.recent_requested.emit(latest_item.data(Qt.ItemDataRole.UserRole))

    def update_delete_button(self) -> None:
        self.delete_button.setEnabled(self.recent_list.currentItem() is not None)

    def delete_selected_project(self) -> None:
        item = self.recent_list.currentItem()
        if item is None:
            return
        path = Path(item.data(Qt.ItemDataRole.UserRole))
        answer = QMessageBox.warning(
            self,
            "Delete project permanently?",
            f"Delete '{path.name}' and every file inside it?\n\n{path}\n\nThis cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            delete_project(path)
            self.refresh()
        except (OSError, ValueError) as exc:
            LOGGER.exception("Could not delete project: %s", path)
            QMessageBox.critical(self, "Could not delete project", str(exc))


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
        self.song_preview_player = QMediaPlayer(self)
        self.song_preview_audio = QAudioOutput(self)
        self.song_preview_audio.setVolume(0.7)
        self.song_preview_player.setAudioOutput(self.song_preview_audio)
        self.song_preview_player.positionChanged.connect(self._song_preview_position_changed)
        self.song_preview_player.durationChanged.connect(self._song_preview_duration_changed)
        self.song_preview_player.mediaStatusChanged.connect(self._song_preview_status_changed)
        self.song_preview_player.errorOccurred.connect(self._song_preview_failed)
        self.active_song_preview_id: str | None = None
        self.active_song_preview_cell: SongPreviewCell | None = None
        self.home_requested.connect(self.stop_song_preview)
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

        self.media_table = QTableWidget(0, 7)
        self.media_table.setHorizontalHeaderLabels(["Clip", "Marks", "Duration", "Resolution", "FPS", "Codec", "Size"])
        self.media_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.media_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.media_table.setSortingEnabled(False)
        header_view = self.media_table.horizontalHeader()
        header_view.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in range(1, 7):
            header_view.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        self.media_table.itemDoubleClicked.connect(lambda *_: self.open_preview())
        
        # Add files and folder buttons with icons
        add_files = QPushButton("Add Files")
        add_files.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_FileIcon))
        add_folder = QPushButton("Add Folder")
        add_folder.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DirIcon))
        self.preview_button = QPushButton("Preview / Edit")
        self.preview_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay))
        add_files.clicked.connect(self.add_files)
        add_folder.clicked.connect(self.add_folder)
        self.preview_button.clicked.connect(self.open_preview)
        
        up = self._tool_button(QStyle.StandardPixmap.SP_ArrowUp, "Move selected clip up", lambda: self.move_selected(-1))
        down = self._tool_button(QStyle.StandardPixmap.SP_ArrowDown, "Move selected clip down", lambda: self.move_selected(1))
        remove = self._tool_button(QStyle.StandardPixmap.SP_TrashIcon, "Remove selected clip", self.remove_selected)
        
        # Actions row
        media_actions = QHBoxLayout()
        media_actions.addWidget(add_files)
        media_actions.addWidget(add_folder)
        media_actions.addWidget(self.preview_button)
        media_actions.addWidget(up)
        media_actions.addWidget(down)
        media_actions.addWidget(remove)
        media_actions.addStretch()
        self.media_total = QLabel("No footage imported")
        self.media_total.setStyleSheet("color: #68716b; font-weight: 500; padding-right: 6px;")
        self.media_total.setMinimumWidth(self.media_total.sizeHint().width())
        media_actions.addWidget(self.media_total)

        # Footage workspace card
        footage_card = QFrame()
        footage_card.setObjectName("produceCard")
        footage_layout = QVBoxLayout(footage_card)
        footage_layout.setContentsMargins(20, 20, 20, 20)
        footage_layout.setSpacing(14)

        # Card Title Header
        footage_header = QHBoxLayout()
        footage_title = QLabel("Imported Clips")
        footage_title.setStyleSheet("font-size: 11pt; font-weight: bold; color: #18342a;")
        footage_header.addWidget(footage_title)
        footage_header.addStretch()
        footage_layout.addLayout(footage_header)

        # Add table and actions into the card
        footage_layout.addWidget(self.media_table, 1)
        footage_layout.addLayout(media_actions)

        # Main panel layout
        media_panel = QWidget()
        media_layout = QVBoxLayout(media_panel)
        media_layout.setContentsMargins(16, 16, 16, 16)
        media_layout.setSpacing(16)
        media_layout.addWidget(footage_card, 1)

        self.workflow_combo = QComboBox()
        self.workflow_combo.addItem("Epic Montage", WorkflowMode.EPIC_MONTAGE)
        self.workflow_combo.addItem("Full-length Video", WorkflowMode.FULL_LENGTH)
        self.workflow_combo.addItem("Real Estate Showcase", WorkflowMode.REAL_ESTATE)
        self.workflow_combo.currentIndexChanged.connect(self.workflow_changed)
        workflow_row = QHBoxLayout()
        workflow_row.addWidget(QLabel("Workflow"))
        workflow_row.addWidget(self.workflow_combo, 1)

        self.epic_panel = self._epic_panel()
        self.full_panel = self._full_panel()
        self.real_estate_panel = self._real_estate_panel()
        self.mode_stack = QStackedWidget()
        self.mode_stack.addWidget(self.epic_panel)
        self.mode_stack.addWidget(self.full_panel)
        self.mode_stack.addWidget(self.real_estate_panel)

        music_panel = QWidget()
        music_layout = QVBoxLayout(music_panel)
        music_layout.setContentsMargins(16, 16, 16, 16)
        music_layout.setSpacing(12)
        music_layout.addLayout(workflow_row)
        music_layout.addWidget(self.mode_stack, 1)

        music_scroll = QScrollArea()
        music_scroll.setWidgetResizable(True)
        music_scroll.setWidget(music_panel)

        # Export options card
        config_card = QFrame()
        config_card.setObjectName("produceCard")
        config_layout = QHBoxLayout(config_card)
        config_layout.setContentsMargins(20, 16, 20, 16)
        config_layout.setSpacing(16)

        export_label = QLabel("Export Resolution:")
        export_label.setStyleSheet("font-weight: bold; color: #18342a;")
        config_layout.addWidget(export_label)

        self.source_export = QCheckBox("Source resolution")
        self.hd_export = QCheckBox("1080p maximum")
        self.source_export.setChecked(True)
        config_layout.addWidget(self.source_export)
        config_layout.addWidget(self.hd_export)
        config_layout.addStretch(1)

        self.render_button = QPushButton("Produce")
        self.render_button.setObjectName("primaryButton")
        self.render_button.clicked.connect(self.start_render)

        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self.cancel_operation)

        config_layout.addWidget(self.render_button)
        config_layout.addWidget(self.cancel_button)

        # Status / Progress card
        status_card = QFrame()
        status_card.setObjectName("produceCard")
        status_layout = QVBoxLayout(status_card)
        status_layout.setContentsMargins(20, 20, 20, 20)
        status_layout.setSpacing(14)

        status_header = QHBoxLayout()
        status_title = QLabel("Production Status")
        status_title.setStyleSheet("font-size: 11pt; font-weight: bold; color: #18342a;")
        status_header.addWidget(status_title)
        status_header.addStretch()
        status_layout.addLayout(status_header)

        # Status message display
        self.status_label = QLabel("Ready")
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet("font-size: 10.5pt; color: #354039;")
        status_layout.addWidget(self.status_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        status_layout.addWidget(self.progress_bar)

        self.results_list = QListWidget()
        self.results_list.itemDoubleClicked.connect(self.open_result)
        self.results_list.setVisible(False)
        self.results_list.setMinimumHeight(140)
        status_layout.addWidget(self.results_list, 1)

        open_folder = QPushButton("Open Renders Folder")
        open_folder.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DirOpenIcon))
        open_folder.clicked.connect(self.open_renders_folder)
        
        folder_layout = QHBoxLayout()
        folder_layout.addWidget(open_folder)
        folder_layout.addStretch()
        status_layout.addLayout(folder_layout)

        # Main Produce tab layout
        produce_panel = QWidget()
        produce_layout = QVBoxLayout(produce_panel)
        produce_layout.setContentsMargins(16, 16, 16, 16)
        produce_layout.setSpacing(16)
        produce_layout.addWidget(config_card)
        produce_layout.addWidget(status_card)
        produce_layout.addStretch(1)

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
        self.song_table.verticalHeader().setDefaultSectionSize(42)
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
        self.full_song_search = QLineEdit()
        self.full_song_search.setPlaceholderText("Search songs, artists, or moods")
        self.full_song_search.textChanged.connect(self.apply_song_filters)
        self.full_mood_filter = QComboBox()
        self.full_energy_filter = QComboBox()
        self.full_mood_filter.currentIndexChanged.connect(self.apply_song_filters)
        self.full_energy_filter.addItems(["All energies", "Low", "Medium", "High"])
        self.full_energy_filter.currentIndexChanged.connect(self.apply_song_filters)
        manage = QPushButton("Manage Library")
        manage.clicked.connect(self.open_library)
        filters = QHBoxLayout()
        filters.addWidget(self.full_song_search, 1)
        filters.addWidget(self.full_mood_filter)
        filters.addWidget(self.full_energy_filter)
        filters.addWidget(manage)
        self.full_song_table = QTableWidget(0, 4)
        self.full_song_table.setHorizontalHeaderLabels(["Song", "Mood", "Cuts", "Length"])
        self.full_song_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.full_song_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.full_song_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.full_song_table.verticalHeader().setDefaultSectionSize(42)
        self.full_song_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in range(1, 4):
            self.full_song_table.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        self.full_song_table.itemSelectionChanged.connect(self.song_selected)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 8, 0, 8)
        layout.addLayout(filters)
        layout.addWidget(self.full_song_table)
        return panel

    def _real_estate_panel(self) -> QWidget:
        panel = QWidget()
        self.re_song_search = QLineEdit()
        self.re_song_search.setPlaceholderText("Search songs, artists, or moods")
        self.re_song_search.textChanged.connect(self.apply_song_filters)
        self.re_mood_filter = QComboBox()
        self.re_energy_filter = QComboBox()
        self.re_mood_filter.currentIndexChanged.connect(self.apply_song_filters)
        self.re_energy_filter.addItems(["All energies", "Low", "Medium", "High"])
        self.re_energy_filter.currentIndexChanged.connect(self.apply_song_filters)
        manage = QPushButton("Manage Library")
        manage.clicked.connect(self.open_library)
        filters = QHBoxLayout()
        filters.addWidget(self.re_song_search, 1)
        filters.addWidget(self.re_mood_filter)
        filters.addWidget(self.re_energy_filter)
        filters.addWidget(manage)
        self.re_song_table = QTableWidget(0, 4)
        self.re_song_table.setHorizontalHeaderLabels(["Song", "Mood", "Cuts", "Length"])
        self.re_song_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.re_song_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.re_song_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.re_song_table.verticalHeader().setDefaultSectionSize(42)
        self.re_song_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in range(1, 4):
            self.re_song_table.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        self.re_song_table.itemSelectionChanged.connect(self.song_selected)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 8, 0, 8)
        layout.addLayout(filters)
        layout.addWidget(self.re_song_table)
        return panel

    def set_project(self, project: Project) -> None:
        self.project = project
        self.project_title.setText(project.settings.name)
        self.project_path.setText(str(project.path))
        workflow_index = self.workflow_combo.findData(project.settings.workflow)
        self.workflow_combo.blockSignals(True)
        self.workflow_combo.setCurrentIndex(max(0, workflow_index))
        self.workflow_combo.blockSignals(False)
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
            excluded = sum(selection.type.value == "exclude" for selection in item.selections)
            required = sum(selection.type.value == "required" for selection in item.selections)
            marks = " / ".join(part for part in (f"R {excluded}" if excluded else "", f"G {required}" if required else "") if part)
            values = [
                item.original_name, marks or "-", _duration(item.duration), f"{item.width} x {item.height}",
                f"{item.fps:.2f}", item.codec, f"{item.size_bytes / 1024 ** 2:.1f} MB",
            ]
            for column, value in enumerate(values):
                table_item = QTableWidgetItem(value)
                if column == 1 and (excluded or required):
                    table_item.setToolTip(f"{excluded} excluded range(s)\n{required} required range(s)")
                self.media_table.setItem(row, column, table_item)
        total_duration = sum(item.duration for item in media)
        total_size = sum(item.size_bytes for item in media)
        self.media_total.setText(f"{len(media)} clips | {_duration(total_duration)} | {total_size / 1024 ** 3:.2f} GB ")
        self.media_total.setMinimumWidth(self.media_total.sizeHint().width())

    def _install_song_preview(
        self,
        table: QTableWidget,
        row: int,
        song_id: str,
        title: str,
        audio_path: Path,
        duration_seconds: float,
    ) -> None:
        cell = SongPreviewCell(title, duration_seconds, table)
        cell.play_requested.connect(
            lambda: self.toggle_song_preview(song_id, audio_path, cell, table, row)
        )
        cell.seek_requested.connect(lambda position: self.seek_song_preview(song_id, position))
        table.setCellWidget(row, 0, cell)

    def toggle_song_preview(
        self,
        song_id: str,
        audio_path: Path,
        cell: SongPreviewCell,
        table: QTableWidget,
        row: int,
    ) -> None:
        table.selectRow(row)
        if self.active_song_preview_id == song_id and self.active_song_preview_cell is cell:
            if cell._playing:
                self.song_preview_player.stop()
                cell.set_position(0)
                cell.set_playing(False)
                self.active_song_preview_id = None
                self.active_song_preview_cell = None
            else:
                cell.set_playing(True)
                self.song_preview_player.play()
            return

        self.stop_song_preview()
        if not audio_path.is_file():
            self.status_label.setText(f"Song file is missing: {audio_path}")
            return
        self.active_song_preview_id = song_id
        self.active_song_preview_cell = cell
        cell.set_position(0)
        cell.set_playing(True)
        self.song_preview_player.setSource(QUrl.fromLocalFile(str(audio_path)))
        self.song_preview_player.play()

    def seek_song_preview(self, song_id: str, position: int) -> None:
        if song_id == self.active_song_preview_id:
            self.song_preview_player.setPosition(position)
            if self.song_preview_player.playbackState() != QMediaPlayer.PlaybackState.PlayingState:
                if self.active_song_preview_cell is not None:
                    self.active_song_preview_cell.set_playing(True)
                self.song_preview_player.play()

    def stop_song_preview(self, animate: bool = False) -> None:
        self.song_preview_player.stop()
        if self.active_song_preview_cell is not None:
            try:
                self.active_song_preview_cell.set_playing(False, animate=animate)
                self.active_song_preview_cell.set_position(0)
            except RuntimeError:
                pass
        self.active_song_preview_id = None
        self.active_song_preview_cell = None

    def _song_preview_position_changed(self, position: int) -> None:
        if self.active_song_preview_cell is not None:
            try:
                self.active_song_preview_cell.set_position(position)
            except RuntimeError:
                self.active_song_preview_cell = None

    def _song_preview_duration_changed(self, duration: int) -> None:
        if self.active_song_preview_cell is not None:
            try:
                self.active_song_preview_cell.set_duration(duration)
            except RuntimeError:
                self.active_song_preview_cell = None

    def _song_preview_status_changed(self, status: QMediaPlayer.MediaStatus) -> None:
        if status == QMediaPlayer.MediaStatus.EndOfMedia and self.active_song_preview_cell is not None:
            self.active_song_preview_cell.set_position(0)
            self.active_song_preview_cell.set_playing(False)

    def _song_preview_failed(self, *_args) -> None:
        message = self.song_preview_player.errorString() or "The song could not be played."
        if hasattr(self, "status_label"):
            self.status_label.setText(message)
        self.stop_song_preview()

    @staticmethod
    def _update_preview_selection(table: QTableWidget) -> None:
        current_row = table.currentRow()
        for row in range(table.rowCount()):
            cell = table.cellWidget(row, 0)
            if isinstance(cell, SongPreviewCell):
                cell.set_selected(row == current_row)

    def refresh_catalog(self, selected_id: str | None = None) -> None:
        self.stop_song_preview()
        try:
            self.songs = load_song_catalog()
        except ValueError as exc:
            self.songs = []
            QMessageBox.critical(self, "Music library error", str(exc))

        # Epic Montage moods & filter
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

        # Full-length Video moods & filter
        full_moods = sorted({mood for song in self.songs if song.workflow == WorkflowMode.FULL_LENGTH for mood in song.moods}, key=str.casefold)
        current_full_mood = self.full_mood_filter.currentText() if hasattr(self, "full_mood_filter") else "All moods"
        if hasattr(self, "full_mood_filter"):
            self.full_mood_filter.blockSignals(True)
            self.full_mood_filter.clear()
            self.full_mood_filter.addItem("All moods", "")
            for mood in full_moods:
                self.full_mood_filter.addItem(mood.title(), mood)
            index = self.full_mood_filter.findText(current_full_mood)
            self.full_mood_filter.setCurrentIndex(max(0, index))
            self.full_mood_filter.blockSignals(False)
            
        # Real Estate Showcase moods & filter
        re_moods = sorted({mood for song in self.songs if song.workflow == WorkflowMode.REAL_ESTATE for mood in song.moods}, key=str.casefold)
        current_re_mood = self.re_mood_filter.currentText() if hasattr(self, "re_mood_filter") else "All moods"
        if hasattr(self, "re_mood_filter"):
            self.re_mood_filter.blockSignals(True)
            self.re_mood_filter.clear()
            self.re_mood_filter.addItem("All moods", "")
            for mood in re_moods:
                self.re_mood_filter.addItem(mood.title(), mood)
            index = self.re_mood_filter.findText(current_re_mood)
            self.re_mood_filter.setCurrentIndex(max(0, index))
            self.re_mood_filter.blockSignals(False)

        self.apply_song_filters(selected_id)

    def apply_song_filters(self, selected_id: str | None = None) -> None:
        if isinstance(selected_id, int):
            selected_id = None
        current_id = selected_id or (self.project.settings.song_id if self.project else None)
        
        # 1. Epic Montage filter
        if hasattr(self, "mood_filter"):
            mood = self.mood_filter.currentData() or ""
            energy = "" if self.energy_filter.currentIndex() == 0 else self.energy_filter.currentText().lower()
            montage_songs = [s for s in self.songs if s.workflow == WorkflowMode.EPIC_MONTAGE]
            filtered = filter_songs(montage_songs, self.song_search.text(), mood, energy)
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
                self._install_song_preview(
                    self.song_table, row, song.song_id, song.title, song.audio_path, song.total_duration_seconds,
                )
                if song.song_id == current_id:
                    selected_row = row
            if selected_row < 0 and filtered:
                selected_row = 0
            if selected_row >= 0:
                self.song_table.selectRow(selected_row)
                self._update_preview_selection(self.song_table)

        # 2. Full-length Video filter. Legacy tracks remain available beside
        # songs added through the managed catalog.
        if hasattr(self, "full_mood_filter"):
            selected_track_id = (
                self.project.settings.full_length_track_id if self.project else "drone-music-1"
            )
            full_mood = self.full_mood_filter.currentData() or ""
            full_energy = "" if self.full_energy_filter.currentIndex() == 0 else self.full_energy_filter.currentText().lower()
            text = self.full_song_search.text().strip().casefold()
            rows: list[tuple[str, str, str, str, str, Path, float]] = []
            full_songs = [s for s in self.songs if s.workflow == WorkflowMode.FULL_LENGTH]
            managed_ids = {song.song_id for song in full_songs}
            if not full_mood and not full_energy:
                for track in FULL_LENGTH_TRACKS:
                    if track.track_id in managed_ids or (track.path.parent / "preset.json").is_file():
                        continue
                    if not text or text in f"{track.title} {track.description}".casefold():
                        rows.append((
                            track.track_id, track.title, track.description, "Full video",
                            _duration(track.duration_seconds), track.path, track.duration_seconds,
                        ))
            for song in filter_songs(full_songs, self.full_song_search.text(), full_mood, full_energy):
                rows.append((
                    song.song_id,
                    song.title,
                    ", ".join(song.moods),
                    str(len(song.cut_timestamps)),
                    _duration(song.total_duration_seconds),
                    song.audio_path,
                    song.total_duration_seconds,
                ))
            self.full_song_table.setRowCount(len(rows))
            selected_full_row = -1
            for row, (track_id, title, mood, cuts, length, audio_path, duration_seconds) in enumerate(rows):
                for column, value in enumerate((title, mood, cuts, length)):
                    item = QTableWidgetItem(value)
                    if column == 0:
                        item.setData(Qt.ItemDataRole.UserRole, track_id)
                    self.full_song_table.setItem(row, column, item)
                self._install_song_preview(
                    self.full_song_table, row, track_id, title, audio_path, duration_seconds,
                )
                if track_id == selected_track_id:
                    selected_full_row = row
            if selected_full_row < 0 and rows:
                selected_full_row = 0
            if selected_full_row >= 0:
                self.full_song_table.selectRow(selected_full_row)
                self._update_preview_selection(self.full_song_table)

        # 3. Real Estate Showcase filter
        if hasattr(self, "re_mood_filter"):
            re_mood = self.re_mood_filter.currentData() or ""
            re_energy = "" if self.re_energy_filter.currentIndex() == 0 else self.re_energy_filter.currentText().lower()
            re_songs = [s for s in self.songs if s.workflow == WorkflowMode.REAL_ESTATE]
            re_filtered = filter_songs(re_songs, self.re_song_search.text(), re_mood, re_energy)
            self.re_song_table.setRowCount(len(re_filtered))
            selected_re_row = -1
            for row, song in enumerate(re_filtered):
                values = [song.title, ", ".join(song.moods), str(len(song.cut_timestamps)), _duration(song.total_duration_seconds)]
                for column, value in enumerate(values):
                    item = QTableWidgetItem(value)
                    if column == 0:
                        item.setData(Qt.ItemDataRole.UserRole, song.song_id)
                        item.setToolTip(f"{song.artist}\nMinimum footage: {_duration(song.minimum_source_duration_seconds)}")
                    self.re_song_table.setItem(row, column, item)
                self._install_song_preview(
                    self.re_song_table, row, song.song_id, song.title, song.audio_path, song.total_duration_seconds,
                )
                if song.song_id == current_id:
                    selected_re_row = row
            if selected_re_row < 0 and re_filtered:
                selected_re_row = 0
            if selected_re_row >= 0:
                self.re_song_table.selectRow(selected_re_row)
                self._update_preview_selection(self.re_song_table)

    def song_selected(self) -> None:
        sender = self.sender()
        if sender in (self.song_table, self.full_song_table, self.re_song_table):
            self._update_preview_selection(sender)
        if not self.project:
            return
        table_workflows = {
            self.song_table: WorkflowMode.EPIC_MONTAGE,
            self.full_song_table: WorkflowMode.FULL_LENGTH,
            self.re_song_table: WorkflowMode.REAL_ESTATE,
        }
        if table_workflows.get(sender) != self.workflow_combo.currentData():
            return
        if sender == self.song_table:
            row = self.song_table.currentRow()
            item = self.song_table.item(row, 0) if row >= 0 else None
            if item:
                self.project.settings.song_id = item.data(Qt.ItemDataRole.UserRole)
        elif sender == self.re_song_table:
            row = self.re_song_table.currentRow()
            item = self.re_song_table.item(row, 0) if row >= 0 else None
            if item:
                self.project.settings.song_id = item.data(Qt.ItemDataRole.UserRole)
        elif sender == self.full_song_table:
            row = self.full_song_table.currentRow()
            item = self.full_song_table.item(row, 0) if row >= 0 else None
            if item:
                self.project.settings.full_length_track_id = item.data(Qt.ItemDataRole.UserRole)

    def workflow_changed(self) -> None:
        self.stop_song_preview()
        workflow = self.workflow_combo.currentData()
        if workflow == WorkflowMode.EPIC_MONTAGE:
            self.mode_stack.setCurrentIndex(0)
            table = self.song_table
        elif workflow == WorkflowMode.FULL_LENGTH:
            self.mode_stack.setCurrentIndex(1)
            table = self.full_song_table
        elif workflow == WorkflowMode.REAL_ESTATE:
            self.mode_stack.setCurrentIndex(2)
            table = self.re_song_table
        else:
            return

        if table.rowCount() == 0:
            return
        if workflow in {WorkflowMode.FULL_LENGTH, WorkflowMode.REAL_ESTATE} or table.currentRow() < 0:
            table.selectRow(0)
        self._update_preview_selection(table)

        if not self.project:
            return
        item = table.item(table.currentRow(), 0)
        if item is None:
            return
        selected_id = item.data(Qt.ItemDataRole.UserRole)
        if workflow == WorkflowMode.FULL_LENGTH:
            self.project.settings.full_length_track_id = selected_id
        else:
            self.project.settings.song_id = selected_id

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

    def open_preview(self) -> None:
        if not self.project or self.thread:
            return
        row = self.selected_media_row()
        if not 0 <= row < len(self.project.settings.media):
            QMessageBox.information(self, "Preview footage", "Select a clip to preview.")
            return
        media = self.project.settings.media[row]
        dialog = ClipPreviewDialog(
            media,
            str(media.resolve(self.project.path)),
            self,
            str(preview_proxy_path(self.project.path, media)),
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.project.settings.schema_version = 2
            save_project(self.project.path, self.project.settings)
            self.refresh_media()
            self.media_table.selectRow(row)

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
        dialog = SongEditorDialog(self.entitlement, self, workflow_filter=self.workflow_combo.currentData())
        selected_id = self.project.settings.song_id if self.project else None
        dialog.catalog_changed.connect(lambda: self.refresh_catalog(selected_id))
        dialog.exec()
        self.refresh_catalog(selected_id)

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
        if workflow in {WorkflowMode.EPIC_MONTAGE, WorkflowMode.REAL_ESTATE} and not song_id:
            msg = "Choose a Real Estate song." if workflow == WorkflowMode.REAL_ESTATE else "Choose an Epic song."
            QMessageBox.warning(self, "Missing song", msg)
            return
        self.project.settings.workflow = workflow
        self.project.settings.exports = exports
        save_project(self.project.path, self.project.settings)
        request = RenderRequest(workflow, exports, song_id, self.project.settings.full_length_track_id)
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
        self.preview_button.setEnabled(not busy)
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


class AppSplashScreen(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowFlags(Qt.WindowType.SplashScreen | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        container = QFrame()
        container.setObjectName("splashCard")

        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(30, 30, 30, 30)
        container_layout.setSpacing(15)
        container_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.logo_label = QLabel()
        self.logo_label.setObjectName("splashLogo")
        self.logo_label.setFixedSize(300, 200)
        self.logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        logo_path = Path(__file__).parent / "assets" / "logo.jpg"
        logo_pixmap = QPixmap(str(logo_path))
        if logo_pixmap.isNull():
            self.logo_label.setText("E2DM2")
            self.logo_label.setStyleSheet("font-size: 32pt; font-weight: bold; color: #246447;")
        else:
            self.logo_label.setPixmap(logo_pixmap.scaled(
                self.logo_label.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            ))

        version_label = QLabel("Version 1.0")
        version_label.setObjectName("splashVersion")
        version_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        status_label = QLabel("Initializing workflows...")
        status_label.setObjectName("splashStatus")
        status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        copyright_label = QLabel("© 2026 E2DM2. All rights reserved.")
        copyright_label.setObjectName("splashCopyright")
        copyright_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        container_layout.addWidget(self.logo_label)
        container_layout.addWidget(version_label)
        container_layout.addWidget(status_label)
        container_layout.addSpacing(10)
        container_layout.addWidget(copyright_label)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(container)

        self.resize(360, 390)
        self.center_on_screen()

    def center_on_screen(self) -> None:
        screen = QGuiApplication.primaryScreen()
        if screen:
            geo = self.frameGeometry()
            geo.moveCenter(screen.availableGeometry().center())
            self.move(geo.topLeft())


class VisibleCheckBox(QCheckBox):
    """Checkbox with a consistently visible indicator across Qt styles."""

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        option = QStyleOptionButton()
        self.initStyleOption(option)
        indicator = self.style().subElementRect(QStyle.SubElement.SE_CheckBoxIndicator, option, self)

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        enabled = self.isEnabled()
        checked = self.isChecked()
        border_color = QColor("#246447" if enabled else "#aeb7b1")
        fill_color = QColor("#246447" if checked and enabled else "#ffffff")
        if checked and not enabled:
            fill_color = QColor("#aeb7b1")

        box = QRectF(indicator).adjusted(1, 1, -1, -1)
        painter.setPen(QPen(border_color, 1.5))
        painter.setBrush(fill_color)
        painter.drawRoundedRect(box, 3, 3)

        if checked:
            painter.setPen(QPen(QColor("#ffffff"), 2.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            x, y, width, height = box.x(), box.y(), box.width(), box.height()
            painter.drawLine(QPointF(x + width * 0.23, y + height * 0.52), QPointF(x + width * 0.43, y + height * 0.72))
            painter.drawLine(QPointF(x + width * 0.43, y + height * 0.72), QPointF(x + width * 0.78, y + height * 0.30))


class OptionsDialog(QDialog):
    def __init__(self, parent: QWidget | None = None, settings: QSettings | None = None) -> None:
        super().__init__(parent)
        self.settings = settings or QSettings()
        self.setWindowTitle("Options")
        self.setModal(True)
        self.setMinimumWidth(520)

        title = QLabel("Options")
        title.setObjectName("optionsTitle")
        subtitle = QLabel("Customize how E2DM2 behaves. More options will appear here as they become available.")
        subtitle.setObjectName("optionsSubtitle")
        subtitle.setWordWrap(True)

        card = QFrame()
        card.setObjectName("optionsCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(20, 18, 20, 18)
        card_layout.setSpacing(8)

        section = QLabel("STARTUP")
        section.setObjectName("optionsSection")
        option_title = QLabel("Splash screen")
        option_title.setObjectName("optionTitle")
        description = QLabel("Show the E2DM2 welcome screen while the application starts.")
        description.setObjectName("optionDescription")
        description.setWordWrap(True)
        self.splash_checkbox = VisibleCheckBox("Show splash screen on startup")
        self.splash_checkbox.setObjectName("splashScreenOption")
        self.splash_checkbox.setChecked(splash_screen_enabled(self.settings))
        self.splash_checkbox.toggled.connect(self._save_splash_preference)

        card_layout.addWidget(section)
        card_layout.addWidget(option_title)
        card_layout.addWidget(description)
        card_layout.addSpacing(4)
        card_layout.addWidget(self.splash_checkbox)

        hint = QLabel("Changes are saved automatically and take effect the next time you launch E2DM2.")
        hint.setObjectName("optionsHint")
        hint.setWordWrap(True)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(14)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addWidget(card)
        layout.addWidget(hint)
        layout.addWidget(buttons)

    def _save_splash_preference(self, enabled: bool) -> None:
        self.settings.setValue(SHOW_SPLASH_SETTING, enabled)
        self.settings.sync()



class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Easy Epic Drone Movie Maker - E2DM2")
        self.setWindowIcon(QIcon(str(APP_ICON_PATH)))
        self.resize(820, 660)
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
        view_menu = self.menuBar().addMenu("View")
        view_menu.addAction(self.log_dock.toggleViewAction())
        view_menu.addSeparator()
        self.options_action = view_menu.addAction("Options...")
        self.options_action.triggered.connect(self.open_options)
        self.home.new_requested.connect(self.new_project)
        self.home.open_requested.connect(self.open_project)
        self.home.recent_requested.connect(lambda path: self.load_project_path(Path(path)))
        self.workspace.home_requested.connect(self.show_home)
        LOGGER.info("E2DM2 main window initialized")
        self.show_home()

    def open_options(self) -> None:
        OptionsDialog(self).exec()

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
QLabel#appTitle { font-size: 23pt; font-weight: 650; color: #18342a; }
QLabel#shortName { font-size: 13pt; color: #9a5b16; }
QFrame#brandCard { background: #fcfcfc; border: 1px solid #d8ded9; border-radius: 10px; }
QFrame#brandCard QLabel { background: transparent; border: 0; }
QLabel#brandLogo { background: #fcfcfc; border: 0; }
QLabel#homeSubtitle { color: #5e6962; font-size: 10.5pt; }
QLabel#sectionTitle { color: #18342a; font-size: 12pt; font-weight: 650; }
QLabel#projectTitle { font-size: 17pt; font-weight: 650; color: #18342a; }
QLabel#mutedLabel { color: #68716b; }
QLineEdit, QComboBox, QTableWidget, QListWidget, QDoubleSpinBox {
    background: #fcfcfc; border: 1px solid #c8cec9; border-radius: 4px; padding: 5px;
}
QAbstractItemView { background-color: #fcfcfc; alternate-background-color: #f7f8f6; }
QAbstractItemView::item:selected { background: #0e54a9; color: #ffffff; }
QAbstractItemView::item:selected:active { background: #0e54a9; color: #ffffff; }
QAbstractItemView::item:selected:!active { background: #0e54a9; color: #ffffff; }
QTableWidget { gridline-color: #e0e4e0; }
QHeaderView::section { background: #e7ebe7; color: #354039; border: 0; border-bottom: 1px solid #c8cec9; padding: 7px; }
QPushButton, QToolButton { background: #fcfcfc; border: 1px solid #b8c0ba; border-radius: 5px; padding: 7px 12px; }
QPushButton:hover, QToolButton:hover { background: #edf1ed; border-color: #789080; }
QPushButton:disabled, QToolButton:disabled { color: #99a19b; background: #eceeec; }
QPushButton#primaryButton { background: #246447; color: white; border-color: #246447; font-weight: 600; }
QPushButton#primaryButton:hover { background: #1c543a; }
QPushButton#destructiveButton { color: #a33131; border-color: #d4aaaa; }
QPushButton#destructiveButton:hover { color: #ffffff; background: #b33a3a; border-color: #b33a3a; }
QProgressBar { background: #e0e4e0; border: 0; border-radius: 4px; height: 16px; text-align: center; }
QProgressBar::chunk { background: #d08a2f; border-radius: 4px; }
QPlainTextEdit#backendLog { background: #171b18; color: #dce6df; border: 1px solid #39433c; font-family: Consolas; font-size: 9pt; }
QTabWidget::pane { border: 1px solid #c8cec9; background: #fcfcfc; }
QTabBar::tab { background: #e7ebe7; padding: 8px 16px; }
QTabBar::tab:selected { background: #fcfcfc; color: #246447; }
QSplitter::handle { background: #d7dcd8; width: 1px; }

/* Options Dialog */
QLabel#optionsTitle { color: #18342a; font-size: 19pt; font-weight: 650; }
QLabel#optionsSubtitle { color: #68716b; font-size: 10pt; }
QFrame#optionsCard {
    background: #fcfcfc;
    border: 1px solid #d3dad4;
    border-radius: 10px;
}
QFrame#optionsCard QLabel, QFrame#optionsCard QCheckBox {
    background: transparent;
    border: 0;
}
QLabel#optionsSection { color: #246447; font-size: 8.5pt; font-weight: 700; }
QLabel#optionTitle { color: #18342a; font-size: 12pt; font-weight: 650; }
QLabel#optionDescription, QLabel#optionsHint { color: #68716b; }
QCheckBox#splashScreenOption { color: #202521; font-weight: 600; spacing: 9px; padding-top: 5px; }
QCheckBox#splashScreenOption::indicator { width: 18px; height: 18px; }

/* Produce Tab Card Design */
QFrame#produceCard {
    background-color: #fcfcfc;
    border: 1px solid #d3dad4;
    border-radius: 8px;
}
QFrame#produceCard QLabel, QFrame#produceCard QCheckBox {
    background: transparent;
}
QFrame#produceCard QTableWidget {
    border: none;
}

/* Splash Screen Design */
QFrame#splashCard {
    background-color: #fcfcfc;
    border: 2px solid #246447;
    border-radius: 12px;
}
QFrame#splashCard QLabel {
    background: transparent;
}
QLabel#splashVersion {
    font-size: 11pt;
    font-weight: 600;
    color: #d08a2f;
}
QLabel#splashStatus {
    font-size: 9.5pt;
    color: #68716b;
    font-style: italic;
}
QLabel#splashCopyright {
    font-size: 8pt;
    color: #99a19b;
}
"""


def create_application() -> QApplication:
    application = QApplication.instance() or QApplication([])
    application.setApplicationName("E2DM2")
    application.setOrganizationName("E2DM2")
    application.setWindowIcon(QIcon(str(APP_ICON_PATH)))
    application.setStyle("Fusion")
    application.setStyleSheet(STYLESHEET)
    return application
