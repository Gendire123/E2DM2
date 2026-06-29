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
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPen,
    QPixmap,
    QPolygonF,
    QResizeEvent,
    QShowEvent,
)
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (
    QApplication,
    QAbstractItemView,
    QGraphicsOpacityEffect,
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
    QMenu,
    QMessageBox,
    QProgressBar,
    QProgressDialog,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSlider,
    QSplitter,
    QStackedWidget,
    QStyle,
    QStyleOptionButton,
    QStyleOptionSlider,
    QStyleOptionViewItem,
    QStyledItemDelegate,
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
PLAYBACK_LATENCY_MS = 300
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


class SoundtrackComboBox(QComboBox):
    """Combo box whose popup keeps the Soundtrack palette on Windows."""

    _POPUP_STYLE = """
        background-color: #FFFFFF;
        border: 1px solid #DDE5E7;
        padding: 0px;
        margin: 0px;
    """

    def showPopup(self) -> None:
        super().showPopup()
        view = self.view()
        popup = view.window()
        if popup is not self.window():
            popup.setStyleSheet(self._POPUP_STYLE)
            if popup.layout() is not None:
                popup.layout().activate()

            content_height = sum(view.sizeHintForRow(row) for row in range(self.count()))
            popup_chrome_height = popup.height() - view.viewport().height()
            target_height = content_height + popup_chrome_height
            available = popup.screen().availableGeometry()
            target_height = min(target_height, available.height())
            if target_height > popup.height():
                geometry = popup.geometry()
                geometry.setHeight(target_height)
                if geometry.bottom() > available.bottom():
                    geometry.moveBottom(available.bottom())
                popup.setGeometry(geometry)


class SmoothTableWidget(QTableWidget):
    """QTableWidget subclass with smooth pixel-based scrolling instead of line-based scrolling."""

    filesDropped = Signal(list)
    deleteRequested = Signal()
    clickedEmpty = Signal()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setAcceptDrops(True)
        
        # Load footage icon for drag & drop placeholder
        icon_path = Path(__file__).parent / "assets" / "icons" / "footage.svg"
        self._placeholder_icon = QIcon(str(icon_path))

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event):
        if event.mimeData().hasUrls():
            paths = []
            for url in event.mimeData().urls():
                local_path = url.toLocalFile()
                if local_path:
                    path_obj = Path(local_path)
                    if path_obj.is_file() and path_obj.suffix.lower() in [".mp4", ".mov", ".m4v"]:
                        paths.append(path_obj)
                    elif path_obj.is_dir():
                        for p in path_obj.rglob("*"):
                            if p.is_file() and p.suffix.lower() in [".mp4", ".mov", ".m4v"]:
                                paths.append(p)
            if paths:
                self.filesDropped.emit(paths)
            event.acceptProposedAction()
        else:
            super().dropEvent(event)

    def paintEvent(self, event):
        super().paintEvent(event)
        if self.rowCount() == 0:
            from PySide6.QtGui import QFont, QFontMetrics
            from PySide6.QtCore import QRect
            
            # Draw placeholder overlay
            painter = QPainter(self.viewport())
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            
            # Viewport dimensions
            w = self.viewport().width()
            h = self.viewport().height()
            
            # Center coordinates
            cx = w // 2
            cy = h // 2
            
            # Draw a beautiful dashed border container
            margin = 24
            rect = QRectF(margin, margin, w - 2 * margin, h - 2 * margin)
            pen = QPen(QColor("#CDD8DC"), 2, Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.setBrush(QColor("#F8FAFB")) # extremely light, subtle background inside
            painter.drawRoundedRect(rect, 12, 12)
            
            # Draw the footage icon in the center
            icon_size = 48
            icon_rect = QRect(cx - icon_size // 2, cy - icon_size - 10, icon_size, icon_size)
            self._placeholder_icon.paint(painter, icon_rect)
            
            # Draw text lines
            font_title = QFont("Segoe UI", 11, QFont.Weight.Bold)
            font_subtitle = QFont("Segoe UI", 9.5, QFont.Weight.Normal)
            
            # Draw main text
            painter.setFont(font_title)
            painter.setPen(QColor("#142033"))
            title_text = "Drag & drop video files here"
            title_metrics = QFontMetrics(font_title)
            title_w = title_metrics.horizontalAdvance(title_text)
            painter.drawText(cx - title_w // 2, cy + 15, title_text)
            
            # Draw helper text
            painter.setFont(font_subtitle)
            painter.setPen(QColor("#66758A"))
            sub_text = "Supports MP4, MOV, and M4V files"
            sub_metrics = QFontMetrics(font_subtitle)
            sub_w = sub_metrics.horizontalAdvance(sub_text)
            painter.drawText(cx - sub_w // 2, cy + 38, sub_text)
            
            painter.end()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self.deleteRequested.emit()
            event.accept()
        else:
            super().keyPressEvent(event)

    def mousePressEvent(self, event) -> None:
        if self.rowCount() == 0 and event.button() == Qt.MouseButton.LeftButton:
            self.clickedEmpty.emit()
            event.accept()
        else:
            super().mousePressEvent(event)


class ClickableLabel(QLabel):
    """QLabel subclass that acts as a clickable hyperlink."""

    clicked = Signal()

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class InlineTitleEdit(QLineEdit):
    cancelled = Signal()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.cancelled.emit()
            event.accept()
            return
        super().keyPressEvent(event)


class SongPreviewCell(QWidget):
    play_requested = Signal()
    seek_requested = Signal(int)

    def __init__(self, title: str, duration_seconds: float, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("songPreviewCell")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._playing = False
        self._selected = False
        self._bg_color_str = "#FFFFFF"
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
        self.progress_slider.setMinimumHeight(28)
        self.progress_slider.setToolTip("Song position")
        self.progress_slider.setVisible(False)
        self.progress_slider.setStyleSheet(
            "QSlider::groove:horizontal { height: 6px; background: #DDE5EF; border-radius: 3px; }"
            "QSlider::sub-page:horizontal { background: #084481; border-radius: 3px; }"
            "QSlider::add-page:horizontal { background: #DDE5EF; border-radius: 3px; }"
            "QSlider::handle:horizontal { width: 18px; height: 18px; margin: -6px 0; background: #ffffff; "
            "border: 2px solid #084481; border-radius: 9px; }"
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
        layout.setContentsMargins(4, 0, 4, 0)
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
        self._bg_color_str = "#EAF2FC" if self._selected else "#FFFFFF"
        foreground = "#0E56AA" if self._selected else "#142033"
        button = "#0E56AA" if self._playing else "#66758A"
        button_hover = "#084481" if self._playing else "#526173"
        border = "#0E56AA" if self._selected else "#CDD8DC"
        self.setStyleSheet(f"QWidget#songPreviewCell {{ background: {self._bg_color_str}; }}")
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
            painter.fillRect(transport_left, 0, self.width() - transport_left, self.height(), QColor(self._bg_color_str))
            painter.end()


from PySide6.QtCore import QThreadPool, QRunnable
from PySide6.QtGui import QPainterPath
from PySide6.QtWidgets import QGraphicsDropShadowEffect

def apply_card_shadow(widget: QWidget, blur: int = 30, y: int = 10, alpha: int = 28) -> None:
    shadow = QGraphicsDropShadowEffect(widget)
    shadow.setBlurRadius(blur)
    shadow.setOffset(0, y)
    shadow.setColor(QColor(15, 35, 45, alpha))
    widget.setGraphicsEffect(shadow)


class ThumbnailSignals(QObject):
    done = Signal(str, str)


class ThumbnailRunnable(QRunnable):
    def __init__(self, clip_path: Path, thumb_path: Path, signals: ThumbnailSignals):
        super().__init__()
        self.clip_path = clip_path
        self.thumb_path = thumb_path
        self.signals = signals

    def run(self):
        try:
            from .thumbnail import thumbnail_is_current, create_thumbnail
            if not thumbnail_is_current(self.clip_path, self.thumb_path):
                create_thumbnail(self.clip_path, self.thumb_path)
            self.signals.done.emit(str(self.clip_path), str(self.thumb_path))
        except Exception as e:
            LOGGER.exception("Failed to generate thumbnail for %s: %s", self.clip_path, e)


class HeroCard(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.hero_pixmap = QPixmap(str(Path(__file__).parent / "assets" / "hero" / "drone-hero.jpg"))
        
    def paintEvent(self, event):
        super().paintEvent(event)
        if self.hero_pixmap.isNull():
            return
            
        from PySide6.QtGui import QPainter, QPainterPath, QImage, QLinearGradient, QBrush, QColor
        from PySide6.QtCore import QRectF, QRect, QPointF, Qt
        
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()), 20, 20)
        painter.setClipPath(path)
        
        # Scale the image to fit the height of the card while maintaining aspect ratio (prevents zoom/cropping)
        img_h = self.height()
        aspect = self.hero_pixmap.width() / self.hero_pixmap.height()
        img_w = int(img_h * aspect)
        
        dest_rect = QRect(self.width() - img_w, 0, img_w, img_h)
        
        temp = QImage(self.size(), QImage.Format.Format_ARGB32)
        temp.fill(Qt.GlobalColor.transparent)
        
        temp_painter = QPainter(temp)
        temp_painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        temp_painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        temp_painter.drawPixmap(dest_rect, self.hero_pixmap)
        
        grad = QLinearGradient(QPointF(self.width() - 550, 0), QPointF(self.width() - 100, 0))
        grad.setColorAt(0.0, QColor(0, 0, 0, 0))
        grad.setColorAt(1.0, QColor(0, 0, 0, 185))
        
        temp_painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
        temp_painter.fillRect(self.rect(), QBrush(grad))
        temp_painter.end()
        
        painter.drawImage(0, 0, temp)
        painter.end()


class ClipFileCell(QWidget):
    def __init__(self, name: str, thumbnail_path_str: str | None = None, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("clipFileCell")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        self.thumb = QLabel()
        self.thumb.setObjectName("clipThumbnail")
        self.thumb.setFixedSize(126, 72)
        self.thumb.setScaledContents(True)

        if thumbnail_path_str:
            pixmap = QPixmap(thumbnail_path_str)
            if not pixmap.isNull():
                rounded_pix = self.get_rounded_pixmap(pixmap, self.thumb.size(), 8)
                self.thumb.setPixmap(rounded_pix)
            else:
                self.set_placeholder()
        else:
            self.set_placeholder()

        self.title = QLabel(name)
        self.title.setObjectName("clipFileName")
        self.title.setWordWrap(True)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(14)
        layout.addWidget(self.thumb)
        layout.addWidget(self.title, 1)

    def set_placeholder(self) -> None:
        self.thumb.setText("Preview")
        self.thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumb.setStyleSheet("background: #E6ECEE; border-radius: 8px; font-weight: bold; color: #66758A;")

    def set_thumbnail(self, thumbnail_path_str: str) -> None:
        pixmap = QPixmap(thumbnail_path_str)
        if not pixmap.isNull():
            rounded_pix = self.get_rounded_pixmap(pixmap, self.thumb.size(), 8)
            self.thumb.setPixmap(rounded_pix)

    def get_rounded_pixmap(self, pixmap: QPixmap, size: QSize, radius: int) -> QPixmap:
        target = QPixmap(size)
        target.fill(Qt.GlobalColor.transparent)
        painter = QPainter(target)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        
        path = QPainterPath()
        path.addRoundedRect(0, 0, size.width(), size.height(), radius, radius)
        painter.setClipPath(path)
        
        scaled = pixmap.scaled(
            size,
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        x = (size.width() - scaled.width()) // 2
        y = (size.height() - scaled.height()) // 2
        painter.drawPixmap(x, y, scaled)
        painter.end()
        return target


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


class FullRowSelectionDelegate(QStyledItemDelegate):
    """Paint selected rows without Qt's extra current-cell focus box."""

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:
        row_option = QStyleOptionViewItem(option)
        row_option.state &= ~QStyle.StateFlag.State_HasFocus
        super().paint(painter, row_option, index)


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
        self.new_button = QPushButton("New Project")
        self.new_button.setObjectName("primaryButton")
        self.open_button = QPushButton("Open Project")
        self.open_button.setObjectName("secondaryButton")
        self.new_button.clicked.connect(self.new_requested)
        self.open_button.clicked.connect(self.open_preferred_project)
        actions = QHBoxLayout()
        actions.addWidget(self.new_button)
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

        self.recent_list = SmoothTableWidget(0, 3)
        self.recent_list.setObjectName("recentProjectsTable")
        self.recent_list.setHorizontalHeaderLabels(["Project title", "Created", "Last modified"])
        self.recent_list.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.recent_list.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.recent_list.setItemDelegate(FullRowSelectionDelegate(self.recent_list))
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

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        if hasattr(self, "onboarding_overlay") and self.onboarding_overlay:
            self.onboarding_overlay.setGeometry(self.rect())


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
        self.thumb_signals = ThumbnailSignals()
        self.thumb_signals.done.connect(self._on_thumbnail_ready)
        self._build_ui()
        self.refresh_catalog()

    @Slot(str, str)
    def _on_thumbnail_ready(self, clip_path: str, thumb_path: str) -> None:
        if not self.project:
            return
        for row in range(self.media_table.rowCount()):
            item = self.project.settings.media[row]
            resolved = str(item.resolve(self.project.path))
            if resolved == clip_path:
                cell = self.media_table.cellWidget(row, 1)
                if isinstance(cell, ClipFileCell):
                    cell.set_thumbnail(thumb_path)
                break

    def _tool_button(self, icon: QStyle.StandardPixmap, tooltip: str, handler) -> QToolButton:
        button = QToolButton()
        button.setIcon(self.style().standardIcon(icon))
        button.setToolTip(tooltip)
        button.clicked.connect(handler)
        return button

    def _build_ui(self) -> None:
        self.setObjectName("workspaceRoot")

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        sidebar = self._build_sidebar()
        root.addWidget(sidebar)

        content = QFrame()
        content.setObjectName("workspaceContent")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(28, 28, 28, 28)
        content_layout.setSpacing(22)

        hero = self._build_project_hero()
        content_layout.addWidget(hero)

        self.workspace_tabs = QStackedWidget()
        self.workspace_tabs.setObjectName("workspaceStack")
        self.workspace_tabs.addWidget(self._build_footage_page())
        self.workspace_tabs.addWidget(self._build_soundtrack_page())
        self.workspace_tabs.addWidget(self._build_produce_page())
        self.workspace_tabs.currentChanged.connect(self._on_tab_changed)
        self.workspace_tabs.currentChanged.connect(self._sync_sidebar_selection)

        content_layout.addWidget(self.workspace_tabs, 1)

        root.addWidget(content, 1)
        self._sync_sidebar_selection(0)

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        self.layout().activate()
        self._align_sidebar_controls()
        if hasattr(self, "_active_sidebar_index"):
            self._place_nav_highlight(self._active_sidebar_index)

        # Trigger workspace onboarding check after shown
        if self.project and not getattr(self, "_onboarding_triggered", False):
            self._onboarding_triggered = True
            QTimer.singleShot(250, self.check_onboarding)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self.layout().activate()
        self._align_sidebar_controls()
        if hasattr(self, "_active_sidebar_index"):
            self._place_nav_highlight(self._active_sidebar_index)

        if hasattr(self, "onboarding_overlay") and self.onboarding_overlay:
            self.onboarding_overlay.setGeometry(self.rect())

    def _align_sidebar_controls(self) -> None:
        if not hasattr(self, "sidebar_logo_spacer") or not hasattr(self, "workspace_tabs"):
            return
        tabs_y = self.workspace_tabs.y()
        logo_bottom = 24 + self.sidebar_logo_label.height()
        spacing = max(0, tabs_y - logo_bottom - 30)
        self.sidebar_logo_spacer.setFixedHeight(spacing)

    def _metric_item(self, value_label: QLabel, caption: str, icon: QIcon | None = None) -> QWidget:
        container = QWidget()
        container.setObjectName("metricItem")

        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        if icon and not icon.isNull():
            icon_label = QLabel()
            icon_label.setObjectName("heroIcon")
            icon_label.setPixmap(icon.pixmap(22, 22))
            layout.addWidget(icon_label)

        value_label.setObjectName("metricValue")
        caption_label = QLabel(caption)
        caption_label.setObjectName("metricCaption")

        text = QVBoxLayout()
        text.setContentsMargins(0, 0, 0, 0)
        text.setSpacing(2)
        text.addWidget(value_label)
        text.addWidget(caption_label)

        layout.addLayout(text)
        return container

    def _build_sidebar(self) -> QWidget:
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")

        self.sidebar_logo_label = QLabel()
        self.sidebar_logo_label.setObjectName("sidebarLogo")
        self.sidebar_logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo_pix = QPixmap(str(Path(__file__).parent / "assets" / "logo_small.jpg"))
        if logo_pix.isNull():
            self.sidebar_logo_label.setText("E2DM2")
            self.sidebar_logo_label.setFixedSize(252, 154)
        else:
            logo_pix.setDevicePixelRatio(self.devicePixelRatioF())
            self.sidebar_logo_label.setPixmap(logo_pix)
            self.sidebar_logo_label.setFixedSize(logo_pix.deviceIndependentSize().toSize())
        sidebar.setFixedWidth(max(252, self.sidebar_logo_label.width()))

        self.sidebar_logo_spacer = QWidget()
        self.sidebar_logo_spacer.setObjectName("sidebarLogoSpacer")
        self.sidebar_logo_spacer.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        self.nav_footage = QPushButton("  Footage")
        self.nav_soundtrack = QPushButton("  Soundtrack")
        self.nav_produce = QPushButton("  Produce")

        self.nav_footage.setIcon(QIcon(str(Path(__file__).parent / "assets" / "icons" / "footage.svg")))
        self.nav_soundtrack.setIcon(QIcon(str(Path(__file__).parent / "assets" / "icons" / "soundtrack.svg")))
        self.nav_produce.setIcon(QIcon(str(Path(__file__).parent / "assets" / "icons" / "produce.svg")))

        self.nav_footage.setObjectName("navButton")
        self.nav_soundtrack.setObjectName("navButton")
        self.nav_produce.setObjectName("navButton")

        self.nav_footage.clicked.connect(lambda: self.workspace_tabs.setCurrentIndex(0))
        self.nav_soundtrack.clicked.connect(lambda: self.workspace_tabs.setCurrentIndex(1))
        self.nav_produce.clicked.connect(lambda: self.workspace_tabs.setCurrentIndex(2))

        self.settings_button = QPushButton("  Settings")
        self.settings_button.setObjectName("sidebarSettings")
        self.settings_button.setIcon(QIcon(str(Path(__file__).parent / "assets" / "icons" / "settings.svg")))
        self.settings_button.clicked.connect(lambda: self.window().open_options())

        self.back_button = QPushButton("  Back to projects")
        self.back_button.setObjectName("sidebarBack")
        self.back_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowBack))
        self.back_button.clicked.connect(self.home_requested.emit)

        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(0, 24, 0, 24)
        layout.setSpacing(16)

        layout.addWidget(self.sidebar_logo_label, 0, Qt.AlignmentFlag.AlignHCenter)
        
        layout.addWidget(self.sidebar_logo_spacer)

        controls = QWidget()
        self.sidebar_controls = controls
        controls_layout = QVBoxLayout(controls)
        controls_layout.setContentsMargins(20, 0, 20, 0)
        controls_layout.setSpacing(16)

        controls_layout.addWidget(self.nav_footage)
        controls_layout.addWidget(self.nav_soundtrack)
        controls_layout.addWidget(self.nav_produce)

        controls_layout.addStretch(1)

        controls_layout.addWidget(self.settings_button)
        controls_layout.addWidget(self.back_button)

        self.nav_selection_highlight = QFrame(controls)
        self.nav_selection_highlight.setObjectName("navSelectionHighlight")
        self.nav_selection_highlight.hide()
        self.nav_selection_highlight.lower()

        self.nav_selection_indicator = QFrame(self.nav_selection_highlight)
        self.nav_selection_indicator.setObjectName("navSelectionIndicator")
        self.nav_selection_indicator.show()
        self.nav_selection_indicator.raise_()
        layout.addWidget(controls, 1)

        return sidebar

    def _build_project_hero(self) -> QWidget:
        hero = HeroCard()
        hero.setObjectName("heroCard")
        apply_card_shadow(hero)

        hero_layout = QHBoxLayout(hero)
        hero_layout.setContentsMargins(24, 24, 24, 24)
        hero_layout.setSpacing(24)

        left_layout = QVBoxLayout()
        left_layout.setSpacing(16)
        left_layout.setContentsMargins(0, 0, 0, 0)

        self.project_title = QLabel("Project Name")
        self.project_title.setObjectName("heroTitle")
        self.project_title_edit = InlineTitleEdit()
        self.project_title_edit.setObjectName("heroTitleEdit")
        self.project_title_edit.setMinimumWidth(440)
        self.project_title_edit.hide()
        self.project_title_edit.editingFinished.connect(self._save_project_title_edit)
        self.project_title_edit.cancelled.connect(self._cancel_project_title_edit)
        self._title_edit_active = False

        self.project_title_edit_button = QToolButton()
        self.project_title_edit_button.setObjectName("heroTitleEditButton")
        self.project_title_edit_button.setIcon(QIcon(str(
            Path(__file__).parent / "assets" / "icons" / "hero-edit.svg"
        )))
        self.project_title_edit_button.setIconSize(QSize(19, 19))
        self.project_title_edit_button.setFixedSize(32, 32)
        self.project_title_edit_button.setToolTip("Edit project title")
        self.project_title_edit_button.setAccessibleName("Edit project title")
        self.project_title_edit_button.setEnabled(False)
        self.project_title_edit_button.clicked.connect(self._begin_project_title_edit)

        title_layout = QHBoxLayout()
        title_layout.setContentsMargins(0, 0, 0, 0)
        title_layout.setSpacing(8)
        title_layout.addWidget(self.project_title)
        title_layout.addWidget(self.project_title_edit)
        title_layout.addWidget(self.project_title_edit_button)
        title_layout.addStretch(1)
        left_layout.addLayout(title_layout)

        metrics_layout = QHBoxLayout()
        metrics_layout.setSpacing(24)
        metrics_layout.setContentsMargins(0, 0, 0, 0)

        self.metric_created_value = QLabel("--")
        self.metric_target_duration_value = QLabel("--")

        icon_root = Path(__file__).parent / "assets" / "icons"
        metric_created = self._metric_item(
            self.metric_created_value, "Created", QIcon(str(icon_root / "hero-calendar.svg")),
        )
        self.metric_target_duration = self._metric_item(
            self.metric_target_duration_value, "Target Duration", QIcon(str(icon_root / "hero-clock.svg")),
        )

        metrics_layout.addWidget(metric_created)
        metrics_layout.addWidget(self.metric_target_duration)
        metrics_layout.addStretch(1)

        left_layout.addLayout(metrics_layout)

        soundtrack_layout = QHBoxLayout()
        soundtrack_layout.setSpacing(10)
        soundtrack_layout.setContentsMargins(0, 0, 0, 0)

        music_icon = QLabel()
        music_icon.setObjectName("heroIcon")
        music_icon.setPixmap(QIcon(str(icon_root / "hero-music.svg")).pixmap(22, 22))
        
        self.hero_soundtrack_title = ClickableLabel("Epic Montage 1 by E2DM2")
        self.hero_soundtrack_title.setObjectName("heroSoundtrackTitle")
        self.hero_soundtrack_title.clicked.connect(lambda: self.workspace_tabs.setCurrentIndex(1))
        
        soundtrack_layout.addWidget(music_icon)
        soundtrack_layout.addWidget(self.hero_soundtrack_title)
        soundtrack_layout.addStretch(1)

        left_layout.addLayout(soundtrack_layout)

        hero_layout.addLayout(left_layout, 1)

        # Compatibility Hidden Labels
        self.project_footage_label = QLabel()
        self.project_footage_label.setObjectName("hiddenCompatibilityLabel")
        self.project_footage_label.setVisible(False)

        self.project_created_label = QLabel()
        self.project_created_label.setObjectName("hiddenCompatibilityLabel")
        self.project_created_label.setVisible(False)

        self.project_music_label = QLabel()
        self.project_music_label.setObjectName("heroSoundtrack")
        self.project_music_label.setVisible(False)

        self.project_path = QLabel()
        self.project_path.setObjectName("mutedLabel")
        self.project_path.setVisible(False)

        compatibility_layout = QHBoxLayout()
        compatibility_layout.addWidget(self.project_footage_label)
        compatibility_layout.addWidget(self.project_created_label)
        compatibility_layout.addWidget(self.project_music_label)
        compatibility_layout.addWidget(self.project_path)
        left_layout.addLayout(compatibility_layout)

        return hero

    def _build_footage_page(self) -> QWidget:
        footage_panel = QWidget()
        footage_layout = QVBoxLayout(footage_panel)
        footage_layout.setContentsMargins(0, 0, 0, 0)
        footage_layout.setSpacing(16)

        card = QFrame()
        card.setObjectName("mainCard")
        apply_card_shadow(card)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(22, 22, 22, 22)
        card_layout.setSpacing(18)

        card_header = QHBoxLayout()
        film_icon = QLabel()
        film_icon.setPixmap(QIcon(str(Path(__file__).parent / "assets" / "icons" / "footage.svg")).pixmap(24, 24))
        
        card_title = QLabel("Imported Clips")
        card_title.setObjectName("cardTitle")

        columns_btn = QPushButton(" Columns")
        columns_btn.setObjectName("secondaryButton")
        columns_btn.setIcon(QIcon(str(Path(__file__).parent / "assets" / "icons" / "columns.svg")))

        columns_menu = QMenu(self)
        self._column_actions = []
        for col_idx in range(9):
            col_name = ["#", "Clip", "Marks", "Duration", "Resolution", "FPS", "Codec", "Size", "Action"][col_idx]
            action = columns_menu.addAction(col_name)
            action.setCheckable(True)
            is_default_unchecked = col_idx in (5, 6) # FPS (5) and Codec (6)
            action.setChecked(not is_default_unchecked)
            self._column_actions.append((action, col_idx))
            def toggle_col(checked, idx=col_idx):
                self.media_table.setColumnHidden(idx, not checked)
            action.triggered.connect(toggle_col)
        columns_btn.setMenu(columns_menu)

        card_header.addWidget(film_icon)
        card_header.addWidget(card_title)
        card_header.addStretch(1)
        card_header.addWidget(columns_btn)

        card_layout.addLayout(card_header)

        self.media_table = SmoothTableWidget(0, 9)
        self.media_table.setHorizontalHeaderLabels([
            "#",
            "Clip",
            "Marks",
            "Duration",
            "Resolution",
            "FPS",
            "Codec",
            "Size",
            "",
        ])
        self.media_table.verticalHeader().setVisible(False)
        self.media_table.verticalHeader().setDefaultSectionSize(96)
        self.media_table.setShowGrid(False)
        self.media_table.setAlternatingRowColors(False)
        self.media_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.media_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.media_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.media_table.setItemDelegate(FullRowSelectionDelegate(self.media_table))
        self.media_table.cellDoubleClicked.connect(lambda *_: self.open_preview())
        self.media_table.filesDropped.connect(self.start_import)
        self.media_table.deleteRequested.connect(self.remove_selected)
        self.media_table.clickedEmpty.connect(self.add_files)

        header = self.media_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for column in range(2, 8):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(8, QHeaderView.ResizeMode.ResizeToContents)

        for action, idx in self._column_actions:
            self.media_table.setColumnHidden(idx, not action.isChecked())

        card_layout.addWidget(self.media_table, 1)

        add_files = QPushButton("Add Files")
        add_files.setObjectName("secondaryButton")
        add_files.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_FileIcon))
        add_files.clicked.connect(self.add_files)
        self.add_files_button = add_files

        add_folder = QPushButton("Add Folder")
        add_folder.setObjectName("secondaryButton")
        add_folder.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DirIcon))
        add_folder.clicked.connect(self.add_folder)
        self.add_folder_button = add_folder

        self.preview_button = QPushButton("Preview / Edit")
        self.preview_button.setObjectName("primaryButton")
        self.preview_button.setIcon(QIcon(str(Path(__file__).parent / "assets" / "icons" / "edit.svg")))
        self.preview_button.clicked.connect(self.open_preview)

        up = self._tool_button(QStyle.StandardPixmap.SP_ArrowUp, "Move selected clip up", lambda: self.move_selected(-1))
        up.setObjectName("squareIconButton")
        self.move_up_button = up

        down = self._tool_button(QStyle.StandardPixmap.SP_ArrowDown, "Move selected clip down", lambda: self.move_selected(1))
        down.setObjectName("squareIconButton")
        self.move_down_button = down

        remove = self._tool_button(QStyle.StandardPixmap.SP_TrashIcon, "Remove selected clip", self.remove_selected)
        remove.setObjectName("squareIconButton")
        remove.setIcon(QIcon(str(Path(__file__).parent / "assets" / "icons" / "remove.svg")))
        remove.setIconSize(QSize(20, 20))
        self.remove_button = remove

        self.media_total = QLabel("No footage imported")
        self.media_total.setObjectName("summaryPill")

        action_height = max(
            add_files.sizeHint().height(),
            add_folder.sizeHint().height(),
            self.preview_button.sizeHint().height(),
        )
        for control in (up, down, remove, self.media_total):
            control.setFixedHeight(action_height)

        action_row = QHBoxLayout()
        action_row.setSpacing(10)
        action_row.setContentsMargins(0, 0, 0, 0)
        action_row.addWidget(add_files)
        action_row.addWidget(add_folder)
        action_row.addWidget(self.preview_button)
        action_row.addWidget(up)
        action_row.addWidget(down)
        action_row.addWidget(remove)
        action_row.addStretch(1)
        action_row.addWidget(self.media_total)

        card_layout.addLayout(action_row)
        footage_layout.addWidget(card, 1)

        return footage_panel

    def _build_soundtrack_page(self) -> QWidget:
        soundtrack_panel = QWidget()
        soundtrack_layout = QVBoxLayout(soundtrack_panel)
        soundtrack_layout.setContentsMargins(0, 0, 0, 0)
        soundtrack_layout.setSpacing(16)

        workflow_card = QFrame()
        workflow_card.setObjectName("mainCard")
        apply_card_shadow(workflow_card)
        w_layout = QHBoxLayout(workflow_card)
        w_layout.setContentsMargins(20, 16, 20, 16)
        w_layout.setSpacing(16)

        workflow_label = QLabel("Workflow")
        workflow_label.setStyleSheet("font-weight: bold; color: #142033;")
        
        self.workflow_combo = SoundtrackComboBox()
        self.workflow_combo.addItem("Epic Montage", WorkflowMode.EPIC_MONTAGE)
        self.workflow_combo.addItem("Full-length Video", WorkflowMode.FULL_LENGTH)
        self.workflow_combo.addItem("Real Estate Showcase", WorkflowMode.REAL_ESTATE)
        self.workflow_combo.addItem("Custom Songs", WorkflowMode.CUSTOM)
        self.workflow_combo.currentIndexChanged.connect(self.workflow_changed)

        w_layout.addWidget(workflow_label)
        w_layout.addWidget(self.workflow_combo, 1)
        
        soundtrack_layout.addWidget(workflow_card)

        library_card = QFrame()
        library_card.setObjectName("mainCard")
        apply_card_shadow(library_card)
        lib_layout = QVBoxLayout(library_card)
        lib_layout.setContentsMargins(20, 20, 20, 20)
        lib_layout.setSpacing(14)

        lib_title = QLabel("Music Library")
        lib_title.setObjectName("cardTitle")
        lib_layout.addWidget(lib_title)

        self.epic_panel = self._epic_panel()
        self.full_panel = self._full_panel()
        self.real_estate_panel = self._real_estate_panel()
        self.custom_panel = self._custom_panel()

        self.mode_stack = QStackedWidget()
        self.mode_stack.setObjectName("modeStack")
        self.mode_stack.addWidget(self.epic_panel)
        self.mode_stack.addWidget(self.full_panel)
        self.mode_stack.addWidget(self.real_estate_panel)
        self.mode_stack.addWidget(self.custom_panel)

        lib_layout.addWidget(self.mode_stack, 1)
        soundtrack_layout.addWidget(library_card, 1)

        soundtrack_scroll = QScrollArea()
        soundtrack_scroll.setFrameShape(QFrame.Shape.NoFrame)
        soundtrack_scroll.setWidgetResizable(True)
        soundtrack_scroll.setWidget(soundtrack_panel)
        return soundtrack_scroll

    def _build_produce_page(self) -> QWidget:
        produce_panel = QWidget()
        produce_layout = QVBoxLayout(produce_panel)
        produce_layout.setContentsMargins(0, 0, 0, 0)
        produce_layout.setSpacing(16)

        config_card = QFrame()
        config_card.setObjectName("mainCard")
        apply_card_shadow(config_card)
        config_layout = QHBoxLayout(config_card)
        config_layout.setContentsMargins(20, 16, 20, 16)
        config_layout.setSpacing(16)

        export_label = QLabel("Export Resolution:")
        export_label.setStyleSheet("font-weight: bold; color: #142033;")
        config_layout.addWidget(export_label)

        self.source_export = VisibleCheckBox("Source resolution")
        self.hd_export = VisibleCheckBox("1080p maximum")
        self.source_export.setChecked(True)
        self.source_export.toggled.connect(lambda checked: self.hd_export.setChecked(False) if checked else None)
        self.hd_export.toggled.connect(lambda checked: self.source_export.setChecked(False) if checked else None)
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

        status_card = QFrame()
        status_card.setObjectName("mainCard")
        apply_card_shadow(status_card)
        status_layout = QVBoxLayout(status_card)
        status_layout.setContentsMargins(20, 20, 20, 20)
        status_layout.setSpacing(14)

        status_header = QHBoxLayout()
        status_title = QLabel("Production Status")
        status_title.setObjectName("cardTitle")
        status_header.addWidget(status_title)
        status_header.addStretch()
        status_layout.addLayout(status_header)

        self.status_label = QLabel("Ready")
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet("font-size: 10.5pt; color: #526173;")
        status_layout.addWidget(self.status_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        status_layout.addWidget(self.progress_bar)

        self.results_list = QListWidget()
        self.results_list.itemDoubleClicked.connect(self.open_result)
        self.results_list.setVisible(False)
        self.results_list.setMinimumHeight(140)
        status_layout.addWidget(self.results_list, 1)

        self.open_renders_folder_button = QPushButton("Open Renders Folder")
        self.open_renders_folder_button.setObjectName("secondaryButton")
        self.open_renders_folder_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DirOpenIcon))
        self.open_renders_folder_button.clicked.connect(self.open_renders_folder)
        
        folder_layout = QHBoxLayout()
        folder_layout.addWidget(self.open_renders_folder_button)
        folder_layout.addStretch()
        status_layout.addLayout(folder_layout)

        produce_layout.addWidget(config_card)
        produce_layout.addWidget(status_card)
        produce_layout.addStretch(1)

        produce_scroll = QScrollArea()
        produce_scroll.setFrameShape(QFrame.Shape.NoFrame)
        produce_scroll.setWidgetResizable(True)
        produce_scroll.setWidget(produce_panel)
        return produce_scroll

    def _sync_sidebar_selection(self, index: int) -> None:
        buttons = [self.nav_footage, self.nav_soundtrack, self.nav_produce]
        previous_index = getattr(self, "_active_sidebar_index", None)

        if previous_index is None:
            self._active_sidebar_index = index
            for i, button in enumerate(buttons):
                button.setProperty("active", i == index)
                button.style().unpolish(button)
                button.style().polish(button)
            QTimer.singleShot(0, lambda: self._place_nav_highlight(index))
            return

        if previous_index == index:
            return

        if hasattr(self, "_nav_highlight_animation"):
            self._nav_highlight_animation.stop()

        self._active_sidebar_index = index
        for i, button in enumerate(buttons):
            button.setProperty("active", i == index)
            button.style().unpolish(button)
            button.style().polish(button)

        target = buttons[index]
        self.nav_selection_highlight.resize(target.size())
        self.nav_selection_highlight.show()
        self.nav_selection_highlight.lower()
        self._size_nav_indicator()

        highlight_animation = QPropertyAnimation(self.nav_selection_highlight, b"pos", self)
        highlight_animation.setDuration(220)
        highlight_animation.setStartValue(self.nav_selection_highlight.pos())
        highlight_animation.setEndValue(target.pos())
        highlight_animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        highlight_animation.finished.connect(lambda: self._place_nav_highlight(index))
        self._nav_highlight_animation = highlight_animation
        highlight_animation.start()

    def _size_nav_indicator(self) -> None:
        height = self.nav_selection_highlight.height()
        self.nav_selection_indicator.setGeometry(0, 6, 4, max(4, height - 12))

    def _place_nav_highlight(self, index: int) -> None:
        button = (self.nav_footage, self.nav_soundtrack, self.nav_produce)[index]
        self.nav_selection_highlight.setGeometry(button.geometry())
        self._size_nav_indicator()
        self.nav_selection_highlight.show()
        self.nav_selection_highlight.lower()

    def _on_tab_changed(self, index: int) -> None:
        # Clear graphics effects on all widgets in the stack to prevent any rendering freeze
        for i in range(self.workspace_tabs.count()):
            w = self.workspace_tabs.widget(i)
            if w:
                w.setGraphicsEffect(None)

        if index == 1 and self.project:
            from .onboarding import soundtrack_onboarding_enabled
            if soundtrack_onboarding_enabled():
                QTimer.singleShot(250, self.show_soundtrack_onboarding)
        elif index == 2 and self.project:
            from .onboarding import produce_onboarding_enabled
            if produce_onboarding_enabled():
                QTimer.singleShot(250, self.show_produce_onboarding)

    def _epic_panel(self) -> QWidget:
        panel = QWidget()
        self.song_search = QLineEdit()
        self.song_search.setPlaceholderText("Search songs, artists, or moods")
        self.song_search.textChanged.connect(self.apply_song_filters)
        self.mood_filter = SoundtrackComboBox()
        self.energy_filter = SoundtrackComboBox()
        self.mood_filter.currentIndexChanged.connect(self.apply_song_filters)
        self.energy_filter.addItems(["All energies", "Low", "Medium", "High"])
        self.energy_filter.currentIndexChanged.connect(self.apply_song_filters)
        self.manage_button = QPushButton("Manage Library")
        self.manage_button.clicked.connect(self.open_library)
        filters = QHBoxLayout()
        filters.addWidget(self.song_search, 1)
        filters.addWidget(self.mood_filter)
        filters.addWidget(self.manage_button)
        self.song_table = SmoothTableWidget(0, 4)
        self.song_table.setHorizontalHeaderLabels(["Song", "Mood", "Cuts", "Length"])
        self.song_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.song_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.song_table.setItemDelegate(FullRowSelectionDelegate(self.song_table))
        self.song_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.song_table.verticalHeader().setDefaultSectionSize(52)
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
        self.full_mood_filter = SoundtrackComboBox()
        self.full_energy_filter = SoundtrackComboBox()
        self.full_mood_filter.currentIndexChanged.connect(self.apply_song_filters)
        self.full_energy_filter.addItems(["All energies", "Low", "Medium", "High"])
        self.full_energy_filter.currentIndexChanged.connect(self.apply_song_filters)
        manage = QPushButton("Manage Library")
        manage.clicked.connect(self.open_library)
        filters = QHBoxLayout()
        filters.addWidget(self.full_song_search, 1)
        filters.addWidget(self.full_mood_filter)
        filters.addWidget(manage)
        self.full_song_table = SmoothTableWidget(0, 4)
        self.full_song_table.setHorizontalHeaderLabels(["Song", "Mood", "Cuts", "Length"])
        self.full_song_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.full_song_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.full_song_table.setItemDelegate(FullRowSelectionDelegate(self.full_song_table))
        self.full_song_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.full_song_table.verticalHeader().setDefaultSectionSize(52)
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
        self.re_mood_filter = SoundtrackComboBox()
        self.re_energy_filter = SoundtrackComboBox()
        self.re_mood_filter.currentIndexChanged.connect(self.apply_song_filters)
        self.re_energy_filter.addItems(["All energies", "Low", "Medium", "High"])
        self.re_energy_filter.currentIndexChanged.connect(self.apply_song_filters)
        manage = QPushButton("Manage Library")
        manage.clicked.connect(self.open_library)
        filters = QHBoxLayout()
        filters.addWidget(self.re_song_search, 1)
        filters.addWidget(self.re_mood_filter)
        filters.addWidget(manage)
        self.re_song_table = SmoothTableWidget(0, 4)
        self.re_song_table.setHorizontalHeaderLabels(["Song", "Mood", "Cuts", "Length"])
        self.re_song_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.re_song_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.re_song_table.setItemDelegate(FullRowSelectionDelegate(self.re_song_table))
        self.re_song_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.re_song_table.verticalHeader().setDefaultSectionSize(52)
        self.re_song_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in range(1, 4):
            self.re_song_table.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        self.re_song_table.itemSelectionChanged.connect(self.song_selected)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 8, 0, 8)
        layout.addLayout(filters)
        layout.addWidget(self.re_song_table)
        return panel

    def _custom_panel(self) -> QWidget:
        panel = QWidget()
        self.custom_song_search = QLineEdit()
        self.custom_song_search.setPlaceholderText("Search songs, artists, or moods")
        self.custom_song_search.textChanged.connect(self.apply_song_filters)
        self.custom_mood_filter = SoundtrackComboBox()
        self.custom_energy_filter = SoundtrackComboBox()
        self.custom_mood_filter.currentIndexChanged.connect(self.apply_song_filters)
        self.custom_energy_filter.addItems(["All energies", "Low", "Medium", "High"])
        self.custom_energy_filter.currentIndexChanged.connect(self.apply_song_filters)
        manage = QPushButton("Manage Library")
        manage.clicked.connect(self.open_library)
        filters = QHBoxLayout()
        filters.addWidget(self.custom_song_search, 1)
        filters.addWidget(self.custom_mood_filter)
        filters.addWidget(manage)
        self.custom_song_table = SmoothTableWidget(0, 4)
        self.custom_song_table.setHorizontalHeaderLabels(["Song", "Mood", "Cuts", "Length"])
        self.custom_song_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.custom_song_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.custom_song_table.setItemDelegate(FullRowSelectionDelegate(self.custom_song_table))
        self.custom_song_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.custom_song_table.verticalHeader().setDefaultSectionSize(52)
        self.custom_song_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in range(1, 4):
            self.custom_song_table.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        self.custom_song_table.itemSelectionChanged.connect(self.song_selected)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 8, 0, 8)
        layout.addLayout(filters)
        layout.addWidget(self.custom_song_table)
        return panel

    def _update_header_details(self) -> None:
        if not self.project:
            return
        
        # Line 1: Project Name
        self.project_title.setText(self.project.settings.name)
        
        # Line 2: Combined file footage length time
        media = self.project.settings.media
        total_duration = sum(item.duration for item in media)
        total_size = sum(item.size_bytes for item in media)
        
        duration_text = _duration(total_duration)
        size_text = f"{total_size / 1024 ** 3:.2f} GB"
        
        self.project_footage_label.setText(
            f"Footage Duration: {duration_text} ({len(media)} clip{'s' if len(media) != 1 else ''}) | {size_text}"
        )
        
        # Line 3: Project created date
        created_dt = None
        try:
            created_dt = datetime.fromisoformat(str(self.project.settings.created_at).replace("Z", "+00:00"))
            if created_dt.tzinfo is not None:
                created_dt = created_dt.astimezone()
        except (TypeError, ValueError):
            if self.project.path:
                try:
                    file_timestamp = self.project.path.stat().st_ctime
                    created_dt = datetime.fromtimestamp(file_timestamp).astimezone()
                except OSError:
                    pass
        if created_dt:
            created_str = created_dt.strftime("%B %d, %Y at %H:%M")
        else:
            created_str = "Unavailable"
        self.project_created_label.setText(f"Created: {created_str}")

        # Line 4: Music Selection information
        workflow = self.workflow_combo.currentData()
        song_id = None
        if workflow == WorkflowMode.FULL_LENGTH:
            song_id = self.project.settings.full_length_track_id
        elif workflow == WorkflowMode.CUSTOM:
            row = self.custom_song_table.currentRow()
            item = self.custom_song_table.item(row, 0) if row >= 0 else None
            song_id = item.data(Qt.ItemDataRole.UserRole) if item else None
        else:
            song_id = self.project.settings.song_id

        target_duration_seconds = None
        if not song_id:
            music_str = "No soundtrack selected"
        else:
            song_title = None
            song_artist = None
            
            song = next((s for s in self.songs if s.song_id == song_id), None)
            if song:
                song_title = song.title
                song_artist = song.artist
                target_duration_seconds = song.total_duration_seconds
            elif workflow == WorkflowMode.FULL_LENGTH:
                for track in FULL_LENGTH_TRACKS:
                    if track.track_id == song_id:
                        song_title = track.title
                        song_artist = "E2DM2"
                        target_duration_seconds = track.duration_seconds
                        break
            
            if song_title:
                artist_info = f" by {song_artist}" if song_artist else ""
                music_str = f"{song_title}{artist_info}"
            else:
                music_str = f"Unknown Soundtrack ({song_id})"
        self.project_music_label.setText(f"Soundtrack: {music_str}")
        
        # Update hero details
        self.metric_created_value.setText(created_str)
        self.metric_target_duration_value.setText(
            _duration(target_duration_seconds) if target_duration_seconds is not None else "Unavailable"
        )
        self.hero_soundtrack_title.setText(music_str)

    def _begin_project_title_edit(self) -> None:
        if not self.project:
            return
        self._title_edit_active = True
        self.project_title_edit.setText(self.project.settings.name)
        self.project_title.hide()
        self.project_title_edit_button.hide()
        self.project_title_edit.show()
        QTimer.singleShot(0, self._focus_project_title_edit)

    def _focus_project_title_edit(self) -> None:
        if self._title_edit_active:
            self.project_title_edit.setFocus(Qt.FocusReason.ShortcutFocusReason)
            self.project_title_edit.selectAll()

    def _finish_project_title_edit(self) -> None:
        self._title_edit_active = False
        self.project_title_edit.hide()
        self.project_title.show()
        self.project_title_edit_button.show()

    def _cancel_project_title_edit(self) -> None:
        if self._title_edit_active:
            self._finish_project_title_edit()

    def _save_project_title_edit(self) -> None:
        if not self._title_edit_active or not self.project:
            return
        title = self.project_title_edit.text().strip()
        if not title:
            self._finish_project_title_edit()
            return

        previous_title = self.project.settings.name
        self.project.settings.name = title
        try:
            save_project(self.project.path, self.project.settings)
        except OSError as exc:
            self.project.settings.name = previous_title
            QMessageBox.critical(self, "Could not rename project", str(exc))
        else:
            self.project_title.setText(title)
        self._finish_project_title_edit()

    def set_project(self, project: Project) -> None:
        self.project = project
        self._onboarding_triggered = False
        self.project_title.setText(project.settings.name)
        self.project_title_edit_button.setEnabled(True)
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
        self._update_header_details()
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
        
        from .thumbnail import thumbnail_path
        
        for row, item in enumerate(media):
            # Column 0: Index "#"
            self.media_table.setItem(row, 0, QTableWidgetItem(str(row + 1)))

            # Column 1: ClipFileCell
            resolved_path = item.resolve(self.project.path)
            thumb_path = thumbnail_path(self.project.path, item)
            
            thumb_path_str = None
            if thumb_path.is_file():
                thumb_path_str = str(thumb_path)
            else:
                # Trigger background thumbnail generation
                runnable = ThumbnailRunnable(resolved_path, thumb_path, self.thumb_signals)
                QThreadPool.globalInstance().start(runnable)

            clip_cell = ClipFileCell(item.original_name, thumb_path_str, self.media_table)
            self.media_table.setCellWidget(row, 1, clip_cell)

            excluded = sum(selection.type.value == "exclude" for selection in item.selections)
            required = sum(selection.type.value == "required" for selection in item.selections)
            marks = " / ".join(part for part in (f"R {excluded}" if excluded else "", f"G {required}" if required else "") if part)

            values = [
                marks or "-",
                _duration(item.duration),
                f"{item.width} x {item.height}",
                f"{item.fps:.2f}",
                item.codec,
                f"{item.size_bytes / 1024 ** 2:.1f} MB",
            ]

            for idx, value in enumerate(values):
                col = idx + 2
                table_item = QTableWidgetItem(value)
                if col == 2 and (excluded or required):
                    table_item.setToolTip(f"{excluded} excluded range(s)\n{required} required range(s)")
                self.media_table.setItem(row, col, table_item)

            menu_button = QToolButton()
            menu_button.setText("⋮")
            menu_button.setObjectName("rowMenuButton")
            menu_button.clicked.connect(lambda _=False, r=row: self._open_clip_row_menu(r))
            self.media_table.setCellWidget(row, 8, menu_button)

        total_duration = sum(item.duration for item in media)
        total_size = sum(item.size_bytes for item in media)
        
        duration_text = _duration(total_duration)
        clips_text = str(len(media))
        size_text = f"{total_size / 1024 ** 3:.2f} GB"
        
        self.media_total.setText(f"{len(media)} clips | {duration_text} | {size_text}")
        self.media_total.setMinimumWidth(self.media_total.sizeHint().width())
        self._update_header_details()

    def _open_clip_row_menu(self, row: int) -> None:
        self.media_table.selectRow(row)
        menu = QMenu(self)
        preview = menu.addAction("Preview / Edit")
        move_up = menu.addAction("Move Up")
        move_down = menu.addAction("Move Down")
        remove = menu.addAction("Remove")
        action = menu.exec(QCursor.pos())
        if action == preview:
            self.open_preview()
        elif action == move_up:
            self.move_selected(-1)
        elif action == move_down:
            self.move_selected(1)
        elif action == remove:
            self.remove_selected()

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
                corrected_position = position
                if self.song_preview_player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
                    corrected_position = max(0, position - PLAYBACK_LATENCY_MS)
                self.active_song_preview_cell.set_position(corrected_position)
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

        # Custom Songs moods & filter
        custom_moods = sorted({mood for song in self.songs if not song.readonly for mood in song.moods}, key=str.casefold)
        current_custom_mood = self.custom_mood_filter.currentText() if hasattr(self, "custom_mood_filter") else "All moods"
        if hasattr(self, "custom_mood_filter"):
            self.custom_mood_filter.blockSignals(True)
            self.custom_mood_filter.clear()
            self.custom_mood_filter.addItem("All moods", "")
            for mood in custom_moods:
                self.custom_mood_filter.addItem(mood.title(), mood)
            index = self.custom_mood_filter.findText(current_custom_mood)
            self.custom_mood_filter.setCurrentIndex(max(0, index))
            self.custom_mood_filter.blockSignals(False)

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

        # 4. Custom Songs filter
        if hasattr(self, "custom_mood_filter"):
            custom_mood = self.custom_mood_filter.currentData() or ""
            custom_energy = "" if self.custom_energy_filter.currentIndex() == 0 else self.custom_energy_filter.currentText().lower()
            custom_songs = [s for s in self.songs if not s.readonly]
            custom_filtered = filter_songs(custom_songs, self.custom_song_search.text(), custom_mood, custom_energy)
            self.custom_song_table.setRowCount(len(custom_filtered))
            selected_custom_row = -1
            for row, song in enumerate(custom_filtered):
                values = [song.title, ", ".join(song.moods), str(len(song.cut_timestamps)), _duration(song.total_duration_seconds)]
                for column, value in enumerate(values):
                    item = QTableWidgetItem(value)
                    if column == 0:
                        item.setData(Qt.ItemDataRole.UserRole, song.song_id)
                        item.setToolTip(f"{song.artist}\nMinimum footage: {_duration(song.minimum_source_duration_seconds)}")
                    self.custom_song_table.setItem(row, column, item)
                self._install_song_preview(
                    self.custom_song_table, row, song.song_id, song.title, song.audio_path, song.total_duration_seconds,
                )
                if song.song_id == current_id:
                    selected_custom_row = row
            if selected_custom_row < 0 and custom_filtered:
                selected_custom_row = 0
            if selected_custom_row >= 0:
                self.custom_song_table.selectRow(selected_custom_row)
                self._update_preview_selection(self.custom_song_table)

    def song_selected(self) -> None:
        sender = self.sender()
        if sender in (self.song_table, self.full_song_table, self.re_song_table, self.custom_song_table):
            self._update_preview_selection(sender)
        if not self.project:
            return
        table_workflows = {
            self.song_table: WorkflowMode.EPIC_MONTAGE,
            self.full_song_table: WorkflowMode.FULL_LENGTH,
            self.re_song_table: WorkflowMode.REAL_ESTATE,
            self.custom_song_table: WorkflowMode.CUSTOM,
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
        elif sender == self.custom_song_table:
            row = self.custom_song_table.currentRow()
            item = self.custom_song_table.item(row, 0) if row >= 0 else None
            if item:
                selected_id = item.data(Qt.ItemDataRole.UserRole)
                song = next((s for s in self.songs if s.song_id == selected_id), None)
                if song:
                    if song.workflow == WorkflowMode.FULL_LENGTH:
                        self.project.settings.full_length_track_id = selected_id
                    else:
                        self.project.settings.song_id = selected_id
                    self.project.settings.workflow = song.workflow
        self._update_header_details()

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
        elif workflow == WorkflowMode.CUSTOM:
            self.mode_stack.setCurrentIndex(3)
            table = self.custom_song_table
        else:
            return

        if table.rowCount() == 0:
            return
        if workflow in {WorkflowMode.FULL_LENGTH, WorkflowMode.REAL_ESTATE, WorkflowMode.CUSTOM} or table.currentRow() < 0:
            table.selectRow(0)
        self._update_preview_selection(table)

        if not self.project:
            return
        item = table.item(table.currentRow(), 0)
        if item is None:
            return
        selected_id = item.data(Qt.ItemDataRole.UserRole)
        if workflow == WorkflowMode.CUSTOM:
            song = next((s for s in self.songs if s.song_id == selected_id), None)
            if song:
                if song.workflow == WorkflowMode.FULL_LENGTH:
                    self.project.settings.full_length_track_id = selected_id
                else:
                    self.project.settings.song_id = selected_id
                self.project.settings.workflow = song.workflow
        elif workflow == WorkflowMode.FULL_LENGTH:
            self.project.settings.full_length_track_id = selected_id
        else:
            self.project.settings.song_id = selected_id
        self._update_header_details()

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

        self.import_dialog = QProgressDialog("Copying footage into the project...", "Cancel", 0, 100, self)
        self.import_dialog.setWindowTitle("Importing Footage")
        self.import_dialog.setWindowModality(Qt.WindowModality.WindowModal)
        self.import_dialog.setAutoClose(True)
        self.import_dialog.setAutoReset(True)
        self.import_dialog.canceled.connect(self.cancel_operation)
        self.import_dialog.setValue(0)
        self.import_dialog.show()

        LOGGER.info("UI started import for %d selected file(s)", len(paths))
        thread.start()

    def import_progress(self, percent: float, name: str) -> None:
        val = round(percent)
        self.progress_bar.setValue(val)
        self.status_label.setText(f"Importing {name}")
        if hasattr(self, "import_dialog") and self.import_dialog:
            self.import_dialog.setLabelText(f"Importing {name}")
            self.import_dialog.setValue(val)

    def import_finished(self, imported) -> None:
        if hasattr(self, "import_dialog") and self.import_dialog:
            self.import_dialog.close()
            self.import_dialog = None
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
        
        main_window = self.window()
        self.preview_page = ClipPreviewDialog(
            media,
            str(media.resolve(self.project.path)),
            main_window,
            str(preview_proxy_path(self.project.path, media)),
        )
        self.preview_page.accepted.connect(lambda: self.on_preview_accepted(row))
        self.preview_page.rejected.connect(self.on_preview_rejected)
        
        main_window.stack.addWidget(self.preview_page)
        main_window.stack.setCurrentWidget(self.preview_page)

    def on_preview_accepted(self, row: int) -> None:
        if not self.project:
            return
        self.project.settings.schema_version = 2
        save_project(self.project.path, self.project.settings)
        self.refresh_media()
        self.media_table.selectRow(row)
        self.cleanup_preview_page()

    def on_preview_rejected(self) -> None:
        self.cleanup_preview_page()

    def cleanup_preview_page(self) -> None:
        if hasattr(self, "preview_page") and self.preview_page:
            self.preview_page.done(0)
            main_window = self.window()
            main_window.stack.setCurrentWidget(self)
            main_window.stack.removeWidget(self.preview_page)
            self.preview_page.deleteLater()
            self.preview_page = None

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
        except (ValueError, Exception) as exc:
            LOGGER.warning("Could not delete file %s: %s", copied_path, exc)
        save_project(self.project.path, self.project.settings)
        self.refresh_media()

    def open_library(self) -> None:
        main_window = self.window()
        self.library_page = SongEditorDialog(self.entitlement, main_window, workflow_filter=self.workflow_combo.currentData())
        selected_id = self.project.settings.song_id if self.project else None
        self.library_page.catalog_changed.connect(lambda: self.refresh_catalog(selected_id))
        self.library_page.accepted.connect(lambda: self.on_library_closed(selected_id))
        self.library_page.rejected.connect(lambda: self.on_library_closed(selected_id))
        
        main_window.stack.addWidget(self.library_page)
        main_window.stack.setCurrentWidget(self.library_page)

    def on_library_closed(self, selected_id: str | None) -> None:
        if hasattr(self, "library_page") and self.library_page:
            self.library_page.player.stop()
            main_window = self.window()
            main_window.stack.setCurrentWidget(self)
            main_window.stack.removeWidget(self.library_page)
            self.library_page.deleteLater()
            self.library_page = None
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
        if workflow == WorkflowMode.CUSTOM:
            selected_row = self.custom_song_table.currentRow()
            if selected_row < 0:
                QMessageBox.warning(self, "Missing song", "Choose a custom song.")
                return
            item = self.custom_song_table.item(selected_row, 0)
            selected_id = item.data(Qt.ItemDataRole.UserRole)
            song = next((s for s in self.songs if s.song_id == selected_id), None)
            if not song:
                QMessageBox.warning(self, "Missing song", "Choose a custom song.")
                return
            workflow = song.workflow
            if workflow == WorkflowMode.FULL_LENGTH:
                self.project.settings.full_length_track_id = selected_id
                song_id = None
            else:
                self.project.settings.song_id = selected_id
                song_id = selected_id
        else:
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
        if hasattr(self, "import_dialog") and self.import_dialog:
            self.import_dialog.close()
            self.import_dialog = None
        self.status_label.setText(message)
        LOGGER.error("UI operation failed: %s", message)
        QMessageBox.critical(self, "Operation failed", message)

    def cancel_operation(self) -> None:
        if self.cancellation:
            self.cancellation.cancel()
            self.status_label.setText("Cancelling...")

    def thread_finished(self) -> None:
        if hasattr(self, "import_dialog") and self.import_dialog:
            self.import_dialog.close()
            self.import_dialog = None
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
        self.nav_footage.setEnabled(not busy)
        self.nav_soundtrack.setEnabled(not busy)
        self.add_files_button.setEnabled(not busy)
        self.add_folder_button.setEnabled(not busy)
        self.move_up_button.setEnabled(not busy)
        self.move_down_button.setEnabled(not busy)
        self.remove_button.setEnabled(not busy)

    def open_result(self, item) -> None:
        path = item.data(Qt.ItemDataRole.UserRole)
        if path:
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))
        else:
            QMessageBox.warning(self, "Render failed", item.toolTip())

    def open_renders_folder(self) -> None:
        if self.project:
            custom_dir = QSettings().value("custom_output_folder", "")
            if custom_dir:
                renders_path = Path(custom_dir)
            else:
                renders_path = self.project.path / "renders"
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(renders_path)))

    def check_onboarding(self) -> None:
        from .onboarding import workspace_onboarding_enabled
        if workspace_onboarding_enabled():
            self.show_onboarding()

    def show_onboarding(self) -> None:
        if hasattr(self, "onboarding_overlay") and self.onboarding_overlay and self.onboarding_overlay.isVisible():
            return
        from .onboarding import OnboardingOverlay
        if not hasattr(self, "onboarding_overlay") or not self.onboarding_overlay:
            self.onboarding_overlay = OnboardingOverlay(self, self.get_onboarding_steps(), "startup/show_workspace_onboarding")
            self.onboarding_overlay.setGeometry(self.rect())
        else:
            self.onboarding_overlay.steps = self.get_onboarding_steps()
        self.onboarding_overlay.show_onboarding()

    def get_onboarding_steps(self) -> list[dict]:
        return [
            {
                "target": lambda ws: ws._get_sidebar_nav_rect(),
                "title": "Three Sections, Three Steps",
                "description": "Navigate between Footage (Import), Soundtrack, and Produce to guide your film editing step-by-step."
            },
            {
                "target": lambda ws: ws._get_table_drop_rect(),
                "title": "Import files by Drag & Drop",
                "description": "Simply drag and drop your drone video files directly into this central area to import them."
            },
            {
                "target": lambda ws: ws._get_add_buttons_rect(),
                "title": "Import via Add Files / Folder",
                "description": "Alternatively, use the Add Files or Add Folder buttons to select footage from your directories."
            },
            {
                "target": lambda ws: ws.preview_button,
                "title": "Preview and Edit Clips",
                "description": "Once files are imported, select any clip and click Preview / Edit to view it or mark key highlights."
            },
            {
                "target": lambda ws: ws._get_move_buttons_rect(),
                "title": "Change Clip Order",
                "description": "Use the Up and Down arrow buttons to change the order in which clips appear in your final movie."
            },
            {
                "target": lambda ws: ws.remove_button,
                "title": "Delete Selected Videos",
                "description": "Remove selected clips from the list by clicking the red X button, or by pressing the Delete key on your keyboard."
            },
            {
                "target": lambda ws: ws.settings_button,
                "title": "Application Settings",
                "description": "Access the Settings here to adjust application preferences and how the E2DM2 backend behaves."
            },
            {
                "target": lambda ws: ws.metric_target_duration,
                "title": "Target Production Duration",
                "description": "This shows the target duration for your movie, which updates automatically based on the soundtrack you select."
            }
        ]

    def _get_sidebar_nav_rect(self) -> QRectF:
        from PySide6.QtCore import QPoint, QRectF
        top_left = self.nav_footage.mapTo(self, QPoint(0, 0))
        bottom_right = self.nav_produce.mapTo(self, QPoint(self.nav_produce.width(), self.nav_produce.height()))
        padding = 8
        return QRectF(
            top_left.x() - padding,
            top_left.y() - padding,
            bottom_right.x() - top_left.x() + 2 * padding,
            bottom_right.y() - top_left.y() + 2 * padding
        )

    def _get_table_drop_rect(self) -> QRectF:
        from PySide6.QtCore import QPoint, QRectF
        viewport = self.media_table.viewport()
        pos = viewport.mapTo(self, QPoint(0, 0))
        margin = 24
        return QRectF(
            pos.x() + margin,
            pos.y() + margin,
            viewport.width() - 2 * margin,
            viewport.height() - 2 * margin
        )

    def _get_add_buttons_rect(self) -> QRectF:
        from PySide6.QtCore import QPoint, QRectF
        top_left = self.add_files_button.mapTo(self, QPoint(0, 0))
        bottom_right = self.add_folder_button.mapTo(self, QPoint(self.add_folder_button.width(), self.add_folder_button.height()))
        padding = 8
        return QRectF(
            top_left.x() - padding,
            top_left.y() - padding,
            bottom_right.x() - top_left.x() + 2 * padding,
            bottom_right.y() - top_left.y() + 2 * padding
        )

    def _get_move_buttons_rect(self) -> QRectF:
        from PySide6.QtCore import QPoint, QRectF
        top_left = self.move_up_button.mapTo(self, QPoint(0, 0))
        bottom_right = self.move_down_button.mapTo(self, QPoint(self.move_down_button.width(), self.move_down_button.height()))
        padding = 8
        return QRectF(
            top_left.x() - padding,
            top_left.y() - padding,
            bottom_right.x() - top_left.x() + 2 * padding,
            bottom_right.y() - top_left.y() + 2 * padding
        )

    def show_soundtrack_onboarding(self) -> None:
        if hasattr(self, "onboarding_overlay") and self.onboarding_overlay and self.onboarding_overlay.isVisible():
            return
        from .onboarding import OnboardingOverlay
        if not hasattr(self, "onboarding_overlay") or not self.onboarding_overlay:
            self.onboarding_overlay = OnboardingOverlay(self, self.get_soundtrack_onboarding_steps(), "startup/show_soundtrack_onboarding")
            self.onboarding_overlay.setGeometry(self.rect())
        else:
            self.onboarding_overlay.steps = self.get_soundtrack_onboarding_steps()
            self.onboarding_overlay.popup.settings_key = "startup/show_soundtrack_onboarding"
        self.onboarding_overlay.show_onboarding()

    def get_soundtrack_onboarding_steps(self) -> list[dict]:
        return [
            {
                "target": lambda ws: ws.workflow_combo,
                "title": "Choose Editing Workflow",
                "description": "Select how you want to build your video:\n• Epic Montage: Cuts clips dynamically to match music beats.\n• Full-length Video: Keeps full clips matched to music.\n• Real Estate Showcase: Special timing optimized for showcasing properties.\n• Custom: Build your own timings."
            },
            {
                "target": lambda ws: ws.song_table,
                "title": "Music Library",
                "description": "Browse the available soundtracks. Click on any song row to select it as the soundtrack for your final video production."
            },
            {
                "target": lambda ws: ws._get_song_play_btn_rect(),
                "title": "Preview Soundtrack",
                "description": "Click the Play button on any song to listen to the music track before choosing it."
            },
            {
                "target": lambda ws: ws.manage_button,
                "title": "Manage Music Library",
                "description": "Click here to view song details, edit track metadata, or (with a Pro license) import your own custom soundtracks.",
                "position": "left"
            }
        ]

    def _get_song_play_btn_rect(self) -> QRectF:
        from PySide6.QtCore import QPoint, QRectF
        cell = self.song_table.cellWidget(0, 0)
        if not cell or not hasattr(cell, "play_button"):
            return QRectF()
        btn = cell.play_button
        top_left = btn.mapTo(self, QPoint(0, 0))
        padding = 4
        return QRectF(
            top_left.x() - padding,
            top_left.y() - padding,
            btn.width() + 2 * padding,
            btn.height() + 2 * padding
        )

    def show_produce_onboarding(self) -> None:
        if hasattr(self, "onboarding_overlay") and self.onboarding_overlay and self.onboarding_overlay.isVisible():
            return
        from .onboarding import OnboardingOverlay
        if not hasattr(self, "onboarding_overlay") or not self.onboarding_overlay:
            self.onboarding_overlay = OnboardingOverlay(self, self.get_produce_onboarding_steps(), "startup/show_produce_onboarding")
            self.onboarding_overlay.setGeometry(self.rect())
        else:
            self.onboarding_overlay.steps = self.get_produce_onboarding_steps()
            self.onboarding_overlay.popup.settings_key = "startup/show_produce_onboarding"
        self.onboarding_overlay.show_onboarding()

    def get_produce_onboarding_steps(self) -> list[dict]:
        return [
            {
                "target": lambda ws: ws._get_export_resolutions_rect(),
                "title": "Export Resolution",
                "description": "Choose your final video resolution. By default, standard 1080p is selected. Pro users can export at Source resolution to output stunning high-definition 4K footage."
            },
            {
                "target": lambda ws: ws.render_button,
                "title": "Produce Video",
                "description": "Once you are satisfied with your selected clips, edits, and soundtrack selection, click this button to start rendering your final movie masterpiece."
            },
            {
                "target": lambda ws: ws.open_renders_folder_button,
                "title": "Access Renders",
                "description": "When rendering finishes, click here to open the renders folder, where you can watch, share, and publish your newly exported movie."
            }
        ]

    def _get_export_resolutions_rect(self) -> QRectF:
        from PySide6.QtCore import QPoint, QRectF
        top_left = self.source_export.mapTo(self, QPoint(0, 0))
        bottom_right = self.hd_export.mapTo(self, QPoint(self.hd_export.width(), self.hd_export.height()))
        padding = 8
        return QRectF(
            top_left.x() - padding,
            top_left.y() - padding,
            bottom_right.x() - top_left.x() + 2 * padding,
            bottom_right.y() - top_left.y() + 2 * padding
        )


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
            self.logo_label.setStyleSheet("font-size: 32pt; font-weight: bold; color: #0E56AA;")
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
        border_color = QColor("#0E56AA" if enabled else "#AEBEC4")
        fill_color = QColor("#0E56AA" if checked and enabled else "#ffffff")
        if checked and not enabled:
            fill_color = QColor("#AEBEC4")

        box = QRectF(indicator).adjusted(1, 1, -1, -1)
        painter.setPen(QPen(border_color, 1.5))
        painter.setBrush(fill_color)
        painter.drawRoundedRect(box, 3, 3)

        if checked:
            painter.setPen(QPen(QColor("#ffffff"), 2.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            x, y, width, height = box.x(), box.y(), box.width(), box.height()
            painter.drawLine(QPointF(x + width * 0.23, y + height * 0.52), QPointF(x + width * 0.43, y + height * 0.72))
            painter.drawLine(QPointF(x + width * 0.43, y + height * 0.72), QPointF(x + width * 0.78, y + height * 0.30))


class OptionsDialog(QWidget):
    closed = Signal()

    def __init__(self, parent: QWidget | None = None, settings: QSettings | None = None) -> None:
        super().__init__(parent)
        self.settings = settings or QSettings()
        self.setWindowTitle("Options")
        self.setMinimumWidth(520)

        title = QLabel("Options")
        title.setObjectName("optionsTitle")
        subtitle = QLabel("Customize how E2DM2 behaves. More options will appear here as they become available.")
        subtitle.setObjectName("optionsSubtitle")
        subtitle.setWordWrap(True)

        # Setup Tab Widget
        self.tab_widget = QTabWidget()
        self.tab_widget.setObjectName("optionsTabWidget")

        # Tab 1: General
        general_tab = QWidget()
        general_layout = QVBoxLayout(general_tab)
        general_layout.setContentsMargins(0, 0, 0, 0)
        general_layout.setSpacing(0)

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

        card_layout.addSpacing(12)

        welcome_title = QLabel("Welcome screen")
        welcome_title.setObjectName("optionTitle")
        welcome_desc = QLabel("Show the welcome dialog and tour selection on application startup.")
        welcome_desc.setObjectName("optionDescription")
        welcome_desc.setWordWrap(True)
        self.welcome_checkbox = VisibleCheckBox("Show welcome screen on startup")
        self.welcome_checkbox.setObjectName("welcomeScreenOption")
        self.welcome_checkbox.setChecked(self.settings.value("startup/show_welcome_modal", True, type=bool))
        self.welcome_checkbox.toggled.connect(self._save_welcome_preference)

        card_layout.addWidget(welcome_title)
        card_layout.addWidget(welcome_desc)
        card_layout.addSpacing(4)
        card_layout.addWidget(self.welcome_checkbox)

        card_layout.addSpacing(16)
        
        output_section = QLabel("OUTPUT")
        output_section.setObjectName("optionsSection")
        output_title = QLabel("Output directory")
        output_title.setObjectName("optionTitle")
        
        output_desc = QLabel("Default: [Project Directory]/renders")
        output_desc.setObjectName("optionDescription")
        output_desc.setWordWrap(True)
        
        self.output_edit = QLineEdit()
        self.output_edit.setReadOnly(True)
        self.output_edit.setPlaceholderText("Using default output directory")
        
        custom_folder = self.settings.value("custom_output_folder", "")
        if custom_folder:
            self.output_edit.setText(custom_folder)
            
        self.browse_button = QPushButton("Browse...")
        self.browse_button.clicked.connect(self._browse_output_folder)
        
        self.clear_button = QPushButton("Reset to Default")
        self.clear_button.clicked.connect(self._clear_output_folder)
        
        output_row = QHBoxLayout()
        output_row.addWidget(self.output_edit, 1)
        output_row.addWidget(self.browse_button)
        output_row.addWidget(self.clear_button)
        
        card_layout.addWidget(output_section)
        card_layout.addWidget(output_title)
        card_layout.addWidget(output_desc)
        card_layout.addSpacing(4)
        card_layout.addLayout(output_row)

        card_layout.addSpacing(16)
        
        onboarding_section = QLabel("ONBOARDING")
        onboarding_section.setObjectName("optionsSection")
        onboarding_title = QLabel("Reset tutorials")
        onboarding_title.setObjectName("optionTitle")
        onboarding_desc = QLabel("Re-enable all welcome screens, workspace tours, and editing walkthroughs.")
        onboarding_desc.setObjectName("optionDescription")
        onboarding_desc.setWordWrap(True)
        
        self.reset_onboarding_btn = QPushButton("Reset Onboarding Tutorials")
        self.reset_onboarding_btn.setObjectName("resetOnboardingOption")
        self.reset_onboarding_btn.clicked.connect(self._reset_onboarding_preferences)
        self.reset_onboarding_btn.setMinimumHeight(32)
        self.reset_onboarding_btn.setStyleSheet("""
            QPushButton#resetOnboardingOption {
                background: #F1F5F9;
                color: #0F172A;
                border: 1px solid #E2E8F0;
                border-radius: 8px;
                padding: 6px 16px;
                font-weight: bold;
            }
            QPushButton#resetOnboardingOption:hover {
                background: #E2E8F0;
            }
        """)

        card_layout.addWidget(onboarding_section)
        card_layout.addWidget(onboarding_title)
        card_layout.addWidget(onboarding_desc)
        card_layout.addSpacing(4)
        
        reset_row = QHBoxLayout()
        reset_row.addWidget(self.reset_onboarding_btn)
        reset_row.addStretch()
        card_layout.addLayout(reset_row)

        general_layout.addWidget(card)
        self.tab_widget.addTab(general_tab, "General")

        # Tab 2: Codec Settings
        codec_tab = QWidget()
        codec_layout = QVBoxLayout(codec_tab)
        codec_layout.setContentsMargins(0, 0, 0, 0)
        codec_layout.setSpacing(0)

        codec_card = QFrame()
        codec_card.setObjectName("optionsCard")
        codec_card_layout = QVBoxLayout(codec_card)
        codec_card_layout.setContentsMargins(20, 18, 20, 18)
        codec_card_layout.setSpacing(8)

        codec_section = QLabel("VIDEO ENCODING")
        codec_section.setObjectName("optionsSection")
        
        codec_lbl = QLabel("Video Codec")
        codec_lbl.setObjectName("optionTitle")
        codec_desc = QLabel("Select the video format and encoder to use for rendering.")
        codec_desc.setObjectName("optionDescription")
        codec_desc.setWordWrap(True)
        
        self.codec_combo = SoundtrackComboBox()
        self.codec_combo.addItems(["H.264 (AVC)", "H.265 (HEVC)"])
        self.codec_combo.setCurrentText(self.settings.value("codec", "H.264 (AVC)"))
        self.codec_combo.currentTextChanged.connect(self._save_codec_preferences)
        
        codec_card_layout.addWidget(codec_section)
        codec_card_layout.addWidget(codec_lbl)
        codec_card_layout.addWidget(codec_desc)
        codec_card_layout.addSpacing(4)
        codec_card_layout.addWidget(self.codec_combo)
        
        codec_card_layout.addSpacing(16)
        
        quality_section = QLabel("COMPRESSION & QUALITY")
        quality_section.setObjectName("optionsSection")
        quality_lbl = QLabel("Target Quality")
        quality_lbl.setObjectName("optionTitle")
        quality_desc = QLabel("Higher percentage yields better visual details but larger file sizes.")
        quality_desc.setObjectName("optionDescription")
        quality_desc.setWordWrap(True)
        
        quality_row = QHBoxLayout()
        self.quality_slider = QSlider(Qt.Orientation.Horizontal)
        self.quality_slider.setMinimumHeight(28)
        self.quality_slider.setRange(10, 100)
        self.quality_slider.setSingleStep(5)
        self.quality_slider.setPageStep(10)
        
        initial_quality = int(self.settings.value("quality", 80))
        self.quality_slider.setValue(initial_quality)
        
        self.quality_val_label = QLabel(f"{initial_quality}%")
        self.quality_val_label.setFixedWidth(40)
        self.quality_val_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.quality_val_label.setStyleSheet("font-weight: bold; color: #142033; background: transparent;")
        
        self.quality_slider.valueChanged.connect(self._on_quality_slider_changed)
        
        quality_row.addWidget(self.quality_slider, 1)
        quality_row.addWidget(self.quality_val_label)
        
        codec_card_layout.addWidget(quality_section)
        codec_card_layout.addWidget(quality_lbl)
        codec_card_layout.addWidget(quality_desc)
        codec_card_layout.addSpacing(4)
        codec_card_layout.addLayout(quality_row)
        
        codec_card_layout.addSpacing(16)
        
        compression_lbl = QLabel("Compression Speed / Preset")
        compression_lbl.setObjectName("optionTitle")
        compression_desc = QLabel("Balances encoding duration against compression efficiency.")
        compression_desc.setObjectName("optionDescription")
        compression_desc.setWordWrap(True)
        
        self.compression_combo = SoundtrackComboBox()
        self.compression_combo.addItems(["Low (Fast render, larger file)", "Medium (Standard)", "High (Slow render, smaller file)"])
        self.compression_combo.setCurrentText(self.settings.value("compression", "Medium (Standard)"))
        self.compression_combo.currentTextChanged.connect(self._save_codec_preferences)
        
        codec_card_layout.addWidget(compression_lbl)
        codec_card_layout.addWidget(compression_desc)
        codec_card_layout.addSpacing(4)
        codec_card_layout.addWidget(self.compression_combo)
        
        codec_card_layout.addSpacing(16)
        
        self.hw_accel_checkbox = VisibleCheckBox("Use GPU hardware acceleration when available")
        self.hw_accel_checkbox.setObjectName("hwAccelOption")
        self.hw_accel_checkbox.setChecked(self.settings.value("hardware_acceleration", True, type=bool))
        self.hw_accel_checkbox.toggled.connect(self._save_codec_preferences)
        
        codec_card_layout.addWidget(self.hw_accel_checkbox)

        codec_layout.addWidget(codec_card)
        self.tab_widget.addTab(codec_tab, "Codec Settings")

        # Dialog main elements
        hint = QLabel("Changes are saved automatically and take effect the next time you launch E2DM2.")
        hint.setObjectName("optionsHint")
        hint.setWordWrap(True)

        close_btn = QPushButton("Close")
        close_btn.setObjectName("primaryButton")
        close_btn.setFixedWidth(140)
        close_btn.clicked.connect(self.close_options)

        button_layout = QHBoxLayout()
        button_layout.addStretch()
        button_layout.addWidget(close_btn)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(14)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addWidget(self.tab_widget)
        layout.addWidget(hint)
        layout.addLayout(button_layout)

    def close_options(self) -> None:
        self.closed.emit()

    def _save_splash_preference(self, enabled: bool) -> None:
        self.settings.setValue(SHOW_SPLASH_SETTING, enabled)
        self.settings.sync()

    def _save_welcome_preference(self, enabled: bool) -> None:
        self.settings.setValue("startup/show_welcome_modal", enabled)
        self.settings.sync()

    def _browse_output_folder(self) -> None:
        current_dir = self.output_edit.text() or str(Path.home())
        selected_dir = QFileDialog.getExistingDirectory(
            self, "Select Output Folder", current_dir
        )
        if selected_dir:
            self.output_edit.setText(selected_dir)
            self.settings.setValue("custom_output_folder", selected_dir)
            self.settings.sync()

    def _clear_output_folder(self) -> None:
        self.output_edit.clear()
        self.settings.remove("custom_output_folder")
        self.settings.sync()

    def _on_quality_slider_changed(self, value: int) -> None:
        self.quality_val_label.setText(f"{value}%")
        self._save_codec_preferences()

    def _save_codec_preferences(self, *args) -> None:
        self.settings.setValue("codec", self.codec_combo.currentText())
        self.settings.setValue("quality", self.quality_slider.value())
        self.settings.setValue("compression", self.compression_combo.currentText())
        self.settings.setValue("hardware_acceleration", self.hw_accel_checkbox.isChecked())
        self.settings.sync()

    def _reset_onboarding_preferences(self) -> None:
        self.settings.setValue("startup/show_welcome_modal", True)
        self.settings.setValue("startup/show_onboarding", True)
        self.settings.setValue("startup/show_workspace_onboarding", True)
        self.settings.setValue("startup/show_preview_onboarding", True)
        self.settings.setValue("startup/show_soundtrack_onboarding", True)
        self.settings.setValue("startup/show_library_onboarding", True)
        self.settings.setValue("startup/show_produce_onboarding", True)
        self.settings.sync()
        self.welcome_checkbox.setChecked(True)
        QMessageBox.information(
            self,
            "Onboarding Reset",
            "All onboarding tutorials and walkthroughs have been re-enabled.",
        )



class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Easy Epic Drone Movie Maker - E2DM2")
        self.setWindowIcon(QIcon(str(APP_ICON_PATH)))
        self.resize(1180, 820)
        self.setMinimumSize(1024, 700)
        self._centered_once = False
        self.options_page = None
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
        self.home_action = view_menu.addAction("Home Screen")
        self.home_action.triggered.connect(self.show_home)
        view_menu.addSeparator()
        view_menu.addAction(self.log_dock.toggleViewAction())
        view_menu.addSeparator()
        self.options_action = view_menu.addAction("Options...")
        self.options_action.triggered.connect(self.open_options)
        self.home.new_requested.connect(self.new_project)
        self.home.open_requested.connect(self.open_project)
        self.home.recent_requested.connect(lambda path: self.load_project_path(Path(path)))
        self.workspace.home_requested.connect(self.show_home)

        # Help Menu / Onboarding Tours
        help_menu = self.menuBar().addMenu("Help")
        home_tour_action = help_menu.addAction("Show Welcome Screen Tour")
        home_tour_action.triggered.connect(self.start_onboarding_tour)
        workspace_tour_action = help_menu.addAction("Show Workspace Tour")
        workspace_tour_action.triggered.connect(self.start_workspace_tour)
        soundtrack_tour_action = help_menu.addAction("Show Soundtrack Tour")
        soundtrack_tour_action.triggered.connect(self.start_soundtrack_tour)
        produce_tour_action = help_menu.addAction("Show Produce Tour")
        produce_tour_action.triggered.connect(self.start_produce_tour)

        LOGGER.info("E2DM2 main window initialized")
        self.show_home()

    def open_options(self) -> None:
        if hasattr(self, "options_page") and self.options_page:
            return
        self.options_page = OptionsDialog(self)
        self.options_page.closed.connect(self.close_options)
        self.stack.addWidget(self.options_page)
        self.prev_stacked_widget = self.stack.currentWidget()
        self.stack.setCurrentWidget(self.options_page)

    def close_options(self) -> None:
        if hasattr(self, "options_page") and self.options_page:
            self.stack.setCurrentWidget(self.prev_stacked_widget)
            self.stack.removeWidget(self.options_page)
            self.options_page.deleteLater()
            self.options_page = None

    def show_home(self) -> None:
        self.home.refresh()
        self.stack.setCurrentWidget(self.home)

    def check_onboarding(self) -> None:
        from .onboarding import onboarding_enabled, welcome_modal_enabled, WelcomeDialog
        if welcome_modal_enabled():
            dialog = WelcomeDialog(self)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                self.show_onboarding()
            return

        if onboarding_enabled():
            self.show_onboarding()

    def show_onboarding(self) -> None:
        from .onboarding import OnboardingOverlay
        if not hasattr(self.home, "onboarding_overlay") or not self.home.onboarding_overlay:
            self.home.onboarding_overlay = OnboardingOverlay(self.home)
            self.home.onboarding_overlay.setGeometry(self.home.rect())
        self.home.onboarding_overlay.show_onboarding()

    def start_onboarding_tour(self) -> None:
        settings = QSettings()
        settings.setValue("startup/show_onboarding", True)
        settings.sync()
        self.show_home()
        QTimer.singleShot(100, self.show_onboarding)

    def start_workspace_tour(self) -> None:
        if not self.workspace.project:
            QMessageBox.information(
                self,
                "Workspace Tour",
                "Please open or create a project first to take the workspace tour.",
            )
            return

        settings = QSettings()
        settings.setValue("startup/show_workspace_onboarding", True)
        settings.sync()

        self.stack.setCurrentWidget(self.workspace)
        self.workspace.workspace_tabs.setCurrentIndex(0)
        QTimer.singleShot(100, self.workspace.show_onboarding)

    def start_soundtrack_tour(self) -> None:
        if not self.workspace.project:
            QMessageBox.information(
                self,
                "Soundtrack Tour",
                "Please open or create a project first to take the soundtrack tour.",
            )
            return

        settings = QSettings()
        settings.setValue("startup/show_soundtrack_onboarding", True)
        settings.sync()

        self.stack.setCurrentWidget(self.workspace)
        self.workspace.workspace_tabs.setCurrentIndex(1)
        QTimer.singleShot(100, self.workspace.show_soundtrack_onboarding)

    def start_produce_tour(self) -> None:
        if not self.workspace.project:
            QMessageBox.information(
                self,
                "Produce Tour",
                "Please open or create a project first to take the produce tour.",
            )
            return

        settings = QSettings()
        settings.setValue("startup/show_produce_onboarding", True)
        settings.sync()

        self.stack.setCurrentWidget(self.workspace)
        self.workspace.workspace_tabs.setCurrentIndex(2)
        QTimer.singleShot(100, self.workspace.show_produce_onboarding)

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

        # Trigger onboarding after the window is shown and layouts settle
        if not getattr(self, "_onboarding_triggered", False):
            self._onboarding_triggered = True
            QTimer.singleShot(200, self.check_onboarding)

    def center_on_active_screen(self) -> None:
        screen = QGuiApplication.screenAt(QCursor.pos()) or self.screen() or QApplication.primaryScreen()
        if not screen:
            return
        frame = self.frameGeometry()
        frame.moveCenter(screen.availableGeometry().center())
        self.move(frame.topLeft())

    def show_maximized_on_active_screen(self) -> None:
        self.center_on_active_screen()
        self._centered_once = True
        self.showMaximized()


STYLESHEET = """
QWidget {
    color: #142033;
    font-family: "Segoe UI";
    font-size: 10.5pt;
}

QMainWindow, QDialog, .HomePage, .WorkspacePage, QFrame#workspaceContent {
    background: #F5F7F8;
}

QFrame#sidebar {
    background: #FFFFFF;
    border-right: 1px solid #E1E8EA;
}

QLabel#sidebarLogo {
    background: transparent;
}

QPushButton#navButton {
    background: transparent;
    border: 0;
    border-radius: 12px;
    color: #526173;
    font-size: 11pt;
    font-weight: 600;
    padding: 14px 18px;
    text-align: left;
}

QPushButton#navButton:hover {
    background: #F1F5F6;
    color: #142033;
}

QPushButton#navButton[active="true"] {
    background: transparent;
    color: #0E56AA;
}

QFrame#navSelectionHighlight {
    background: #EAF2FC;
    border: 0;
    border-radius: 12px;
}

QFrame#navSelectionIndicator {
    background: #0E56AA;
    border: 0;
    border-radius: 2px;
}

QPushButton#sidebarSettings {
    background: transparent;
    border: 0;
    border-radius: 12px;
    color: #526173;
    font-size: 11pt;
    font-weight: 600;
    padding: 14px 18px;
    text-align: left;
}
QPushButton#sidebarSettings:hover {
    background: #F1F5F6;
    color: #142033;
}

QPushButton#sidebarBack {
    background: transparent;
    border: 0;
    border-radius: 12px;
    color: #526173;
    font-size: 11pt;
    font-weight: 600;
    padding: 14px 18px;
    text-align: left;
}
QPushButton#sidebarBack:hover {
    background: #F1F5F6;
    color: #142033;
}

QFrame#workspaceContent {
    background: #F5F7F8;
}

QFrame#heroCard {
    background: #FFFFFF;
    border: 1px solid #DDE5E7;
    border-radius: 20px;
}

QFrame#heroCard QLabel {
    background: transparent;
    border: 0;
}

QLabel#heroTitle {
    background: transparent;
    color: #142033;
    font-size: 24pt;
    font-weight: 800;
}

QLineEdit#heroTitleEdit {
    background: #FFFFFF;
    color: #142033;
    border: 2px solid #0E56AA;
    border-radius: 8px;
    padding: 3px 8px;
    font-size: 22pt;
    font-weight: 800;
    selection-background-color: #0E56AA;
    selection-color: #FFFFFF;
}

QToolButton#heroTitleEditButton {
    background: transparent;
    border: 0;
    border-radius: 7px;
    padding: 5px;
}

QToolButton#heroTitleEditButton:hover {
    background: #EAF2FC;
}

QLabel#metricValue {
    background: transparent;
    color: #142033;
    font-size: 13pt;
    font-weight: 700;
}

QLabel#metricCaption {
    background: transparent;
    color: #66758A;
    font-size: 9pt;
}

QLabel#heroSoundtrackTitle {
    background: transparent;
    color: #0E56AA;
    font-size: 12pt;
    font-weight: 700;
}

QLabel#heroSoundtrackTitle:hover {
    color: #084481;
    text-decoration: underline;
}

QFrame#mainCard {
    background: #FFFFFF;
    border: 1px solid #DDE5E7;
    border-radius: 16px;
}

QFrame#mainCard QLabel {
    background: transparent;
}

QLabel#cardTitle {
    background: transparent;
    color: #142033;
    font-size: 14pt;
    font-weight: 800;
}

QTableWidget {
    background: #FFFFFF;
    border: 1px solid #DDE5E7;
    border-radius: 12px;
    gridline-color: transparent;
    selection-background-color: #EAF2FC;
    selection-color: #142033;
}

QScrollArea, QScrollArea > QWidget, QScrollArea > QWidget > QWidget {
    background: #F5F7F8;
    border: none;
}

/* Scrollbar Custom Styling */
QScrollBar:vertical {
    border: 1px solid transparent;
    background: #F5F7F8;
    width: 10px;
    margin: 0px;
    border-top-right-radius: 11px;
    border-bottom-right-radius: 11px;
}

QScrollBar::handle:vertical {
    background: #CDD8DC;
    min-height: 20px;
    border-radius: 5px;
}

QScrollBar::handle:vertical:hover {
    background: #AEBEC4;
}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    border: none;
    background: none;
    height: 0px;
}

QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
    background: none;
}

QScrollBar:horizontal {
    border: 1px solid transparent;
    background: #F5F7F8;
    height: 10px;
    margin: 0px;
    border-bottom-left-radius: 11px;
    border-bottom-right-radius: 11px;
}

QScrollBar::handle:horizontal {
    background: #CDD8DC;
    min-width: 20px;
    border-radius: 5px;
}

QScrollBar::handle:horizontal:hover {
    background: #AEBEC4;
}

QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    border: none;
    background: none;
    width: 0px;
}

QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {
    background: none;
}

/* ComboBox Dropdown Styling */
QComboBoxPrivateContainer {
    background-color: #FFFFFF;
    background: #FFFFFF;
    border: 1px solid #DDE5E7;
    padding: 0px;
    margin: 0px;
}

QComboBox QFrame {
    border: 1px solid #DDE5E7;
    background-color: #FFFFFF;
    background: #FFFFFF;
}

QComboBox QAbstractItemView {
    border: none;
    background-color: #FFFFFF;
    background: #FFFFFF;
    selection-background-color: #EAF2FC;
    selection-color: #142033;
    outline: none;
    padding: 0px;
    margin: 0px;
}

QStackedWidget, QStackedWidget > QWidget {
    background: #F5F7F8;
}
QStackedWidget#modeStack, QStackedWidget#modeStack > QWidget {
    background: transparent;
}

QSplitter, QSplitter > QWidget {
    background: #F5F7F8;
}

QTableWidget, QTableWidget > QWidget {
    background: #FFFFFF;
}

QHeaderView {
    background: #F7FAFA;
    border: 1px solid transparent;
    border-top-left-radius: 11px;
    border-top-right-radius: 11px;
}
QHeaderView::section {
    background: #F7FAFA;
}

QHeaderView::section:selected {
    background: #EAF2FC;
    color: #0E56AA;
}

QTabWidget::pane {
    border: 1px solid #DDE5E7;
    background: #FFFFFF;
    border-radius: 12px;
}

QTabWidget#optionsTabWidget::pane {
    border: 0;
    background: transparent;
}

QTabWidget#optionsTabWidget::tab-bar {
    left: 0px;
}

QTabWidget > QWidget, QTabWidget > QStackedWidget > QWidget {
    background: #FFFFFF;
}

QTabWidget#optionsTabWidget > QWidget, QTabWidget#optionsTabWidget > QStackedWidget > QWidget {
    background: transparent;
}

QTabWidget > QTabBar {
    background: #F5F7F8;
}

QTabBar::tab {
    background: #E6ECEE;
    color: #526173;
    padding: 8px 16px;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
    margin-right: 4px;
    font-weight: 600;
}

QTabBar::tab:selected {
    background: #FFFFFF;
    color: #0E56AA;
    border: 1px solid #DDE5E7;
    border-bottom-color: #FFFFFF;
}

QTableWidget::item {
    padding: 8px;
    border-bottom: 1px solid #EEF2F3;
}

QTableWidget::item:selected {
    background: #EAF2FC;
    color: #142033;
}

QHeaderView::section:horizontal {
    background: #F7FAFA;
    color: #526173;
    border: 1px solid transparent;
    border-bottom: 1px solid #DDE5E7;
    padding: 12px 10px;
    font-weight: 700;
}

QHeaderView::section:vertical {
    background: #F7FAFA;
    color: #526173;
    border: 1px solid transparent;
    border-right: 1px solid #DDE5E7;
    padding: 2px 8px;
    font-weight: 700;
}

QTableCornerButton::section {
    background: #F7FAFA;
    border: 1px solid transparent;
    border-bottom: 1px solid #DDE5E7;
    border-right: 1px solid #DDE5E7;
    border-top-left-radius: 11px;
}

QHeaderView::section:horizontal:last {
    border-top-right-radius: 11px;
    border: 1px solid transparent;
    border-bottom: 1px solid #DDE5E7;
}

QHeaderView::section:vertical:last {
    border-bottom-left-radius: 11px;
    border: 1px solid transparent;
    border-right: 1px solid #DDE5E7;
}

QPushButton, QToolButton {
    background: #FFFFFF;
    color: #142033;
    border: 1px solid #CDD8DC;
    border-radius: 10px;
    padding: 12px 22px;
    font-weight: 600;
}

QPushButton:hover, QToolButton:hover {
    background: #F7FAFA;
    border-color: #AEBEC4;
}

QPushButton:pressed, QToolButton:pressed {
    background: #EEF2F3;
}

QPushButton:disabled, QToolButton:disabled {
    background: #E6ECEE;
    color: #8A98A8;
    border-color: #DDE5E7;
}

QPushButton#primaryButton {
    background: #0E56AA;
    color: #FFFFFF;
    border: 1px solid #0E56AA;
    border-radius: 10px;
    padding: 12px 22px;
    font-weight: 700;
}

QPushButton#primaryButton:hover {
    background: #084481;
    border-color: #084481;
}

QPushButton#secondaryButton {
    background: #FFFFFF;
    color: #142033;
    border: 1px solid #CDD8DC;
    border-radius: 10px;
    padding: 12px 22px;
    font-weight: 600;
}

QPushButton#secondaryButton:hover {
    background: #F7FAFA;
    border-color: #AEBEC4;
}

QToolButton#squareIconButton {
    background: #FFFFFF;
    color: #142033;
    border: 1px solid #CDD8DC;
    border-radius: 10px;
    padding: 10px;
    min-width: 42px;
}

QToolButton#squareIconButton:hover {
    background: #F7FAFA;
    border-color: #AEBEC4;
}

QLabel#summaryPill {
    background: #FFFFFF;
    color: #66758A;
    border: 1px solid #DDE5E7;
    border-radius: 10px;
    padding: 11px 18px;
    font-weight: 600;
}

QToolButton#rowMenuButton {
    background: transparent;
    border: 0;
    color: #66758A;
    font-size: 18pt;
    padding: 4px;
}

QToolButton#rowMenuButton:hover {
    background: #F1F5F6;
    border-radius: 8px;
}

QProgressBar {
    background: #EEF2F6;
    color: #000000;
    border: 1px solid #CDD8DC;
    border-radius: 6px;
    height: 18px;
    text-align: center;
    font-weight: bold;
    font-size: 9pt;
}

QProgressBar::chunk {
    background: #90CAF9;
    border-radius: 5px;
}

QPlainTextEdit#backendLog {
    background: #141B26;
    color: #DDE5EF;
    border: 1px solid #34445A;
    font-family: Consolas;
    font-size: 9pt;
}

QSplitter::handle {
    background: #DDE5E7;
    width: 1px;
}

/* Options Dialog */
QLabel#optionsTitle {
    color: #142033;
    font-size: 19pt;
    font-weight: 700;
}
QLabel#optionsSubtitle {
    color: #66758A;
    font-size: 10pt;
}
QFrame#optionsCard {
    background: #FFFFFF;
    border: 1px solid #DDE5E7;
    border-radius: 16px;
}
QFrame#optionsCard QLabel, QFrame#optionsCard QCheckBox {
    background: transparent;
    border: 0;
}
QLabel#optionsSection {
    color: #0E56AA;
    font-size: 8.5pt;
    font-weight: 700;
}
QLabel#optionTitle {
    color: #142033;
    font-size: 12pt;
    font-weight: 700;
}
QLabel#optionDescription, QLabel#optionsHint {
    color: #66758A;
}
QCheckBox#splashScreenOption {
    color: #142033;
    font-weight: 600;
    spacing: 9px;
    padding-top: 5px;
}
QCheckBox#splashScreenOption::indicator {
    width: 18px;
    height: 18px;
}

/* Splash Screen Design */
QFrame#splashCard {
    background-color: #FFFFFF;
    border: 2px solid #0E56AA;
    border-radius: 12px;
}
QFrame#splashCard QLabel {
    background: transparent;
}
QLabel#splashVersion {
    font-size: 11pt;
    font-weight: 600;
    color: #0E56AA;
}
QLabel#splashStatus {
    font-size: 9.5pt;
    color: #66758A;
    font-style: italic;
}
QLabel#splashCopyright {
    font-size: 8pt;
    color: #8A98A8;
}

/* Home Screen Specifics */
QLabel#appTitle {
    font-size: 26pt;
    font-weight: 800;
    color: #142033;
}
QLabel#shortName {
    font-size: 14pt;
    color: #0E56AA;
    font-weight: 700;
}
QFrame#brandCard {
    background: #FFFFFF;
    border: 1px solid #DDE5E7;
    border-radius: 16px;
}
QFrame#brandCard QLabel {
    background: transparent;
    border: 0;
}
QLabel#brandLogo {
    background: #FFFFFF;
    border: 0;
}
QLabel#homeSubtitle {
    color: #66758A;
    font-size: 10.5pt;
}
QLabel#sectionTitle {
    color: #142033;
    font-size: 12pt;
    font-weight: 700;
}
QLabel#projectTitle {
    font-size: 18pt;
    font-weight: 800;
    color: #142033;
}
QLabel#mutedLabel {
    color: #66758A;
}
QLineEdit, QComboBox, QListWidget, QDoubleSpinBox {
    background: #FFFFFF;
    border: 1px solid #DDE5E7;
    border-radius: 8px;
    padding: 6px;
    color: #142033;
}
QAbstractItemView {
    background-color: #FFFFFF;
    alternate-background-color: #F7FAFA;
}
QAbstractItemView::item:selected {
    background: #EAF2FC;
    color: #142033;
}
QAbstractItemView::item:selected:active {
    background: #EAF2FC;
    color: #142033;
}
QAbstractItemView::item:selected:!active {
    background: #EAF2FC;
    color: #142033;
}

/* Custom QSlider Styling */
QSlider::groove:horizontal {
    height: 6px;
    background: #DDE5EF;
    border-radius: 3px;
}
QSlider::sub-page:horizontal {
    background: #084481;
    border-radius: 3px;
}
QSlider::add-page:horizontal {
    background: #DDE5EF;
    border-radius: 3px;
}
QSlider::handle:horizontal {
    width: 18px;
    height: 18px;
    margin: -6px 0;
    background: #ffffff;
    border: 2px solid #084481;
    border-radius: 9px;
}

/* Custom QMenu/Popup styling to ensure readability */
QMenu {
    background-color: #FFFFFF;
    color: #142033;
    border: 1px solid #DDE5E7;
    padding: 4px 0px;
}

QMenu::item {
    background-color: transparent;
    padding: 6px 28px 6px 12px;
    color: #142033;
}

QMenu::item:selected {
    background-color: #EAF2FC;
    color: #0E56AA;
}

QMenu::separator {
    height: 1px;
    background: #E1E8EA;
    margin: 4px 0px;
}

QMenu::indicator {
    width: 14px;
    height: 14px;
    border: 1px solid #CDD8DC;
    border-radius: 3px;
    background-color: #FFFFFF;
    margin-left: 10px;
}

QMenu::indicator:checked {
    background-color: #0E56AA;
    border-color: #0E56AA;
    image: url("data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCAyNCAyNCIgZmlsbD0ibm9uZSIgc3Ryb2tlPSJ3aGl0ZSIgc3Ryb2tlLXdpZHRoPSIzIiBzdHJva2UtbGluZWNhcD0icm91bmQiIHN0cm9rZS1saW5lam9pbj0icm91bmQiPjxwb2x5bGluZSBwb2ludHM9IjIwIDYgOSAxNyA0IDEyIj48L3BvbHlsaW5lPjwvc3ZnPg==");
}

QMenu::indicator:unchecked {
    background-color: #FFFFFF;
    border-color: #CDD8DC;
    image: none;
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
