from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QEvent, QPoint, QPointF, QProcess, QRectF, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QBrush, QColor, QIcon, QKeySequence, QMouseEvent, QPainter, QPen, QPixmap, QShortcut
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QBoxLayout,
    QButtonGroup,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .models import (
    ClipSelection,
    MediaItem,
    SelectionType,
    validate_clip_selections,
)
from .media import preview_proxy_arguments, preview_proxy_is_current


def format_timecode(milliseconds: int) -> str:
    milliseconds = max(0, int(milliseconds))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{millis:03d}"


PLAYBACK_LATENCY_MS = 300

EXCLUDE_COLOR = "#D92D20"
EXCLUDE_COLOR_DARK = "#B42318"
EXCLUDE_COLOR_LIGHT = "#FEF3F2"

REQUIRED_COLOR = "#2EAD4A"
REQUIRED_COLOR_DARK = "#1F7A35"
REQUIRED_COLOR_LIGHT = "#ECFDF3"

PLAYHEAD_COLOR = "#1976D2"
TEXT_DARK = "#142033"
TEXT_MUTED = "#66758A"
BORDER_COLOR = "#DDE5E7"
CARD_BACKGROUND = "#FFFFFF"

PREVIEW_DIALOG_STYLES = f"""
QFrame#selectionModePanel {{
    background: #FFFFFF;
    border: 1px solid {BORDER_COLOR};
    border-radius: 10px;
}}

QLabel#selectionModeHeader {{
    color: #142033;
    font-size: 13.5pt;
    font-weight: 800;
}}

QPushButton#excludeModeButton,
QPushButton#requiredModeButton {{
    background: #FFFFFF;
    color: {TEXT_DARK};
    border: 1px solid #CDD8DC;
    border-radius: 10px;
    padding: 2px;
    font-size: 9.5pt;
    font-weight: 800;
    text-align: left;
}}

QPushButton#excludeModeButton:hover {{
    background: {EXCLUDE_COLOR_LIGHT};
    border-color: {EXCLUDE_COLOR};
}}

QPushButton#requiredModeButton:hover {{
    background: {REQUIRED_COLOR_LIGHT};
    border-color: {REQUIRED_COLOR};
}}

QPushButton#excludeModeButton[modeActive="true"] {{
    background: {EXCLUDE_COLOR};
    color: #FFFFFF;
    border: 2px solid {EXCLUDE_COLOR_DARK};
}}

QPushButton#requiredModeButton[modeActive="true"] {{
    background: {REQUIRED_COLOR};
    color: #FFFFFF;
    border: 2px solid {REQUIRED_COLOR_DARK};
}}

QFrame#currentModeCard,
QFrame#modeLegendCard {{
    background: #FFFFFF;
    border: 1px solid {BORDER_COLOR};
    border-radius: 8px;
}}

QFrame#currentModeCard[mode="exclude"] {{
    background: {EXCLUDE_COLOR_LIGHT};
    border: 1px solid {EXCLUDE_COLOR};
}}

QFrame#currentModeCard[mode="required"] {{
    background: {REQUIRED_COLOR_LIGHT};
    border: 1px solid {REQUIRED_COLOR};
}}

QLabel#currentModeTitle {{
    color: {TEXT_DARK};
    font-weight: 700;
    font-size: 9pt;
}}

QLabel#currentModeInstruction {{
    color: #526173;
    font-size: 8.5pt;
}}

QLabel#excludeLegendDot {{
    color: {EXCLUDE_COLOR};
    font-size: 11pt;
}}

QLabel#requiredLegendDot {{
    color: {REQUIRED_COLOR};
    font-size: 11pt;
}}

QLabel#timelineHelpLabel {{
    color: {TEXT_MUTED};
    font-size: 8.5pt;
}}

QPushButton#playButton {{
    background: #FFFFFF;
    border: 1px solid #CDD8DC;
    border-radius: 6px;
    min-width: 32px;
    max-width: 32px;
    min-height: 32px;
    max-height: 32px;
    padding: 0;
}}
QPushButton#playButton:hover {{
    background: #F7FAFA;
    border-color: #AEBEC4;
}}
QPushButton#playButton:pressed {{
    background: #EEF2F3;
}}

QPushButton#fullscreenButton {{
    background: #FFFFFF;
    border: 1px solid #CDD8DC;
    border-radius: 6px;
    padding: 6px 14px;
    font-weight: 600;
    font-size: 9.5pt;
    height: 20px;
}}
QPushButton#fullscreenButton:hover {{
    background: #F7FAFA;
    border-color: #AEBEC4;
}}
QPushButton#fullscreenButton:pressed {{
    background: #EEF2F3;
}}

QPushButton#saveButton {{
    background: #2F80ED;
    color: #FFFFFF;
    border: 1px solid #1B6FD1;
    border-radius: 8px;
    padding: 8px 20px;
    font-size: 9.5pt;
    font-weight: 800;
    min-width: 90px;
}}
QPushButton#saveButton:hover {{
    background: #1B6FD1;
}}
QPushButton#cancelButton {{
    background: #FFFFFF;
    color: #526173;
    border: 1px solid #CDD8DC;
    border-radius: 8px;
    padding: 8px 20px;
    font-size: 9.5pt;
    font-weight: 800;
    min-width: 90px;
}}
QPushButton#cancelButton:hover {{
    background: #F5F7F8;
    border-color: #B0BEC5;
}}

QProgressBar {{
    background-color: #EEF2F6;
    border: 1px solid #CDD8DC;
    border-radius: 6px;
    text-align: center;
    color: #000000;
    font-weight: bold;
    font-size: 9pt;
}}

QProgressBar::chunk {{
    background-color: #90CAF9;
    border-radius: 5px;
}}
"""


def parse_timecode(value: str) -> int:
    text = value.strip()
    try:
        clock, millis_text = text.rsplit(".", 1)
        hours_text, minutes_text, seconds_text = clock.split(":")
        if len(millis_text) != 3:
            raise ValueError
        hours, minutes, seconds, millis = (
            int(hours_text), int(minutes_text), int(seconds_text), int(millis_text)
        )
        if min(hours, minutes, seconds, millis) < 0 or minutes >= 60 or seconds >= 60 or millis >= 1000:
            raise ValueError
        return hours * 3_600_000 + minutes * 60_000 + seconds * 1000 + millis
    except (ValueError, TypeError) as exc:
        raise ValueError("Use timecode format HH:MM:SS.mmm.") from exc


class SelectionTimeline(QWidget):
    selectionChanged = Signal(int)
    rangeCreated = Signal(object, int, int)
    rangeEdited = Signal(int, int, int)
    positionPreviewed = Signal(int)
    toolChanged = Signal(object)

    HANDLE_WIDTH = 7

    def __init__(self, duration_ms: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.duration_ms = max(1, duration_ms)
        self.selections: list[ClipSelection] = []
        self.selected_index = -1
        self.tool = SelectionType.EXCLUDE
        self._drag_mode: str | None = None
        self._drag_index = -1
        self._drag_offset_ms = 0
        self._anchor_ms = 0
        self._preview_start: int | None = None
        self._preview_end: int | None = None
        self.playhead_ms = 0
        self.hover_ms: int | None = None
        self.setMinimumHeight(86)
        self.setMouseTracking(True)

    def set_selections(self, selections: list[ClipSelection], selected_index: int = -1) -> None:
        self.selections = [replace(selection) for selection in selections]
        self.selected_index = selected_index if 0 <= selected_index < len(selections) else -1
        self.update()

    def set_tool(self, selection_type: SelectionType) -> None:
        if self.tool is selection_type:
            return
        self.tool = selection_type
        self.toolChanged.emit(selection_type)
        self.update()

    def set_playhead(self, position_ms: int) -> None:
        self.playhead_ms = max(0, min(position_ms, self.duration_ms))
        self.update()

    def _track_rect(self) -> QRectF:
        return QRectF(14, 26, max(1, self.width() - 28), 30)

    def _x_for_ms(self, value: int) -> float:
        rect = self._track_rect()
        return rect.left() + rect.width() * max(0, min(value, self.duration_ms)) / self.duration_ms

    def _ms_for_x(self, value: float) -> int:
        rect = self._track_rect()
        ratio = (value - rect.left()) / max(rect.width(), 1)
        return round(max(0.0, min(ratio, 1.0)) * self.duration_ms)

    def _selection_at(self, x: float) -> int:
        value = self._ms_for_x(x)
        for index in range(len(self.selections) - 1, -1, -1):
            selection = self.selections[index]
            if selection.start_ms <= value <= selection.end_ms:
                return index
        return -1

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt API
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self._track_rect()
        painter.fillRect(rect, QColor("#DDE5E7"))
        painter.setPen(QPen(QColor("#7B8CA3"), 1))
        for tick in range(11):
            x = rect.left() + rect.width() * tick / 10
            painter.drawLine(round(x), round(rect.top() - 5), round(x), round(rect.bottom() + 5))
        for index, selection in enumerate(self.selections):
            if index == self.selected_index and self._preview_start is not None and self._preview_end is not None:
                start, end = sorted((self._preview_start, self._preview_end))
            else:
                start, end = selection.start_ms, selection.end_ms
            color = QColor(REQUIRED_COLOR) if selection.type is SelectionType.REQUIRED else QColor(EXCLUDE_COLOR)
            color.setAlpha(205)
            selection_rect = QRectF(
                self._x_for_ms(start), rect.top(),
                max(2, self._x_for_ms(end) - self._x_for_ms(start)), rect.height(),
            )
            painter.fillRect(selection_rect, color)
            if index == self.selected_index:
                painter.setPen(QPen(QColor("#142033"), 2))
                painter.drawRect(selection_rect)
                painter.fillRect(QRectF(selection_rect.left() - 2, rect.top(), 5, rect.height()), QColor("#fcfcfc"))
                painter.fillRect(QRectF(selection_rect.right() - 2, rect.top(), 5, rect.height()), QColor("#fcfcfc"))
        if self._preview_start is not None and self._preview_end is not None and self._drag_mode == "create":
            start, end = sorted((self._preview_start, self._preview_end))
            color = QColor(REQUIRED_COLOR) if self.tool is SelectionType.REQUIRED else QColor(EXCLUDE_COLOR)
            color.setAlpha(130)
            painter.fillRect(
                QRectF(self._x_for_ms(start), rect.top(), max(2, self._x_for_ms(end) - self._x_for_ms(start)), rect.height()),
                color,
            )
        playhead_x = self._x_for_ms(self.playhead_ms)
        painter.setPen(QPen(QColor(PLAYHEAD_COLOR), 2))
        painter.drawLine(round(playhead_x), round(rect.top() - 4), round(playhead_x), round(rect.bottom() + 4))
        if self.hover_ms is not None:
            hover_x = self._x_for_ms(self.hover_ms)
            painter.setPen(QPen(QColor("#f2a900"), 1, Qt.PenStyle.DashLine))
            painter.drawLine(round(hover_x), round(rect.top() - 7), round(hover_x), round(rect.bottom() + 7))
            hover_label = format_timecode(self.hover_ms)
            label_width = painter.fontMetrics().horizontalAdvance(hover_label)
            label_x = max(10, min(self.width() - label_width - 10, round(hover_x - label_width / 2)))
            painter.setPen(QColor("#526173"))
            painter.drawText(label_x, round(rect.bottom() + 20), hover_label)
        painter.setPen(QColor("#526173"))
        painter.drawText(10, 16, format_timecode(0))
        end_label = format_timecode(self.duration_ms)
        painter.drawText(max(10, self.width() - 10 - painter.fontMetrics().horizontalAdvance(end_label)), 16, end_label)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt API
        if event.button() != Qt.MouseButton.LeftButton:
            return
        x = event.position().x()
        position = self._ms_for_x(x)
        self.hover_ms = position
        self.positionPreviewed.emit(position)

        # Check if clicking near the edge handle of any existing selection
        for index, selection in enumerate(self.selections):
            start_x = self._x_for_ms(selection.start_ms)
            end_x = self._x_for_ms(selection.end_ms)
            if abs(x - start_x) <= self.HANDLE_WIDTH:
                self.selected_index = index
                self.selectionChanged.emit(index)
                self._drag_mode = "start"
                self._drag_index = index
                self.update()
                return
            elif abs(x - end_x) <= self.HANDLE_WIDTH:
                self.selected_index = index
                self.selectionChanged.emit(index)
                self._drag_mode = "end"
                self._drag_index = index
                self.update()
                return

        selected = self._selection_at(x)
        if selected >= 0:
            self.selected_index = selected
            self.selectionChanged.emit(selected)
            self._drag_mode = "move"
            self._drag_index = selected
            self._drag_offset_ms = position - self.selections[selected].start_ms
            self._preview_start = self.selections[selected].start_ms
            self._preview_end = self.selections[selected].end_ms
            self.update()
            return
        self.selected_index = -1
        self.selectionChanged.emit(-1)
        self._drag_mode = "create"
        self._anchor_ms = self._ms_for_x(x)
        self._preview_start = self._anchor_ms
        self._preview_end = self._anchor_ms
        self.update()

    def _update_cursor(self, x: float) -> None:
        near_handle = False
        inside_selection = False
        if self._drag_mode in {"start", "end"}:
            near_handle = True
        elif self._drag_mode == "move":
            inside_selection = True
        elif not self._drag_mode:
            for selection in self.selections:
                start_x = self._x_for_ms(selection.start_ms)
                end_x = self._x_for_ms(selection.end_ms)
                if abs(x - start_x) <= self.HANDLE_WIDTH or abs(x - end_x) <= self.HANDLE_WIDTH:
                    near_handle = True
                    break
            if not near_handle:
                value = self._ms_for_x(x)
                for selection in self.selections:
                    if selection.start_ms <= value <= selection.end_ms:
                        inside_selection = True
                        break

        if near_handle:
            self.setCursor(Qt.CursorShape.SizeHorCursor)
        elif inside_selection:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        else:
            self.setCursor(Qt.CursorShape.ArrowCursor)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt API
        x = event.position().x()
        value = self._ms_for_x(x)
        self.hover_ms = value
        self.positionPreviewed.emit(value)
        self._update_cursor(x)
        if not self._drag_mode:
            self.update()
            return
        if self._drag_mode == "create":
            self._preview_end = value
        elif self._drag_mode == "move":
            if 0 <= self._drag_index < len(self.selections):
                selection = self.selections[self._drag_index]
                duration = selection.end_ms - selection.start_ms
                new_start = value - self._drag_offset_ms
                new_start = max(0, min(new_start, self.duration_ms - duration))
                new_end = new_start + duration
                self._preview_start = new_start
                self._preview_end = new_end
        elif 0 <= self._drag_index < len(self.selections):
            selection = self.selections[self._drag_index]
            self._preview_start = value if self._drag_mode == "start" else selection.start_ms
            self._preview_end = value if self._drag_mode == "end" else selection.end_ms
        self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt API
        if event.button() != Qt.MouseButton.LeftButton or not self._drag_mode:
            return
        x = event.position().x()
        value = self._ms_for_x(x)
        self.hover_ms = value
        self.positionPreviewed.emit(value)
        if self._drag_mode == "create":
            start, end = sorted((self._anchor_ms, value))
            if start != end:
                self.rangeCreated.emit(self.tool, start, end)
        elif self._drag_mode == "move" and 0 <= self._drag_index < len(self.selections):
            selection = self.selections[self._drag_index]
            duration = selection.end_ms - selection.start_ms
            new_start = value - self._drag_offset_ms
            new_start = max(0, min(new_start, self.duration_ms - duration))
            new_end = new_start + duration
            self.rangeEdited.emit(self._drag_index, new_start, new_end)
        elif 0 <= self._drag_index < len(self.selections):
            selection = self.selections[self._drag_index]
            start = value if self._drag_mode == "start" else selection.start_ms
            end = value if self._drag_mode == "end" else selection.end_ms
            self.rangeEdited.emit(self._drag_index, start, end)
        self._drag_mode = None
        self._drag_index = -1
        self._preview_start = None
        self._preview_end = None
        self._update_cursor(x)
        self.update()

    def leaveEvent(self, event) -> None:  # noqa: N802 - Qt API
        self.hover_ms = None
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.update()
        super().leaveEvent(event)


class PreviewVideoWidget(QVideoWidget):
    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt API
        if event.key() == Qt.Key.Key_Escape and self.isFullScreen():
            self.setFullScreen(False)
            event.accept()
            return
        super().keyPressEvent(event)
class AspectWidget(QWidget):
    def __init__(self, child: QWidget, ratio: float = 16.0 / 9.0, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.child = child
        self.ratio = ratio
        self.on_resize_callback = None
        child.setParent(self)

    def sizeHint(self) -> QSize:
        return QSize(round(260 * self.ratio), 260)

    def minimumSizeHint(self) -> QSize:
        return QSize(round(260 * self.ratio), 260)

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt API
        super().resizeEvent(event)
        w = self.width()
        h = self.height()
        if h <= 0 or w <= 0:
            return
        if w / h > self.ratio:
            new_h = h
            new_w = round(h * self.ratio)
        else:
            new_w = w
            new_h = round(w / self.ratio)
        x = (w - new_w) // 2
        y = (h - new_h) // 2
        self.child.setGeometry(x, y, new_w, new_h)
        if self.on_resize_callback:
            self.on_resize_callback(x, new_w)



class ClipPreviewDialog(QWidget):
    accepted = Signal()
    rejected = Signal()

    def accept(self) -> None:
        self.accepted.emit()

    def reject(self) -> None:
        self.rejected.emit()

    def create_exclude_table_icon(self) -> QIcon:
        pixmap = QPixmap(64, 64)
        pixmap.fill(Qt.GlobalColor.transparent)
        pixmap.setDevicePixelRatio(4.0)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QColor(EXCLUDE_COLOR))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(QRectF(1.0, 1.0, 14.0, 14.0))
        painter.setPen(QPen(Qt.GlobalColor.white, 2.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawLine(QPointF(4.0, 8.0), QPointF(12.0, 8.0))
        painter.end()
        return QIcon(pixmap)

    def create_required_table_icon(self) -> QIcon:
        pixmap = QPixmap(64, 64)
        pixmap.fill(Qt.GlobalColor.transparent)
        pixmap.setDevicePixelRatio(4.0)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor(REQUIRED_COLOR), 2.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        painter.drawLine(QPointF(4.0, 8.0), QPointF(7.0, 11.0))
        painter.drawLine(QPointF(7.0, 11.0), QPointF(12.0, 4.0))
        painter.end()
        return QIcon(pixmap)

    def create_exclude_button_icons(self) -> tuple[QPixmap, QPixmap]:
        # Inactive: red circle, white minus
        pixmap_inactive = QPixmap(128, 128)
        pixmap_inactive.fill(Qt.GlobalColor.transparent)
        pixmap_inactive.setDevicePixelRatio(4.0)
        painter = QPainter(pixmap_inactive)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QColor(EXCLUDE_COLOR))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(QRectF(1.0, 1.0, 30.0, 30.0))
        painter.setPen(QPen(Qt.GlobalColor.white, 3.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawLine(QPointF(8.0, 16.0), QPointF(24.0, 16.0))
        painter.end()

        # Active: white circle, red minus
        pixmap_active = QPixmap(128, 128)
        pixmap_active.fill(Qt.GlobalColor.transparent)
        pixmap_active.setDevicePixelRatio(4.0)
        painter = QPainter(pixmap_active)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(Qt.GlobalColor.white)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(QRectF(1.0, 1.0, 30.0, 30.0))
        painter.setPen(QPen(QColor(EXCLUDE_COLOR), 3.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawLine(QPointF(8.0, 16.0), QPointF(24.0, 16.0))
        painter.end()

        return pixmap_inactive, pixmap_active

    def create_required_button_icons(self) -> tuple[QPixmap, QPixmap]:
        # Inactive: white circle with gray border, green checkmark
        pixmap_inactive = QPixmap(128, 128)
        pixmap_inactive.fill(Qt.GlobalColor.transparent)
        pixmap_inactive.setDevicePixelRatio(4.0)
        painter = QPainter(pixmap_inactive)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor("#CDD8DC"), 1.5))
        painter.setBrush(Qt.GlobalColor.white)
        painter.drawEllipse(QRectF(1.0, 1.0, 30.0, 30.0))
        painter.setPen(QPen(QColor(REQUIRED_COLOR), 3.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        painter.drawLine(QPointF(9.0, 16.0), QPointF(14.0, 21.0))
        painter.drawLine(QPointF(14.0, 21.0), QPointF(22.0, 10.0))
        painter.end()

        # Active: white circle, green checkmark
        pixmap_active = QPixmap(128, 128)
        pixmap_active.fill(Qt.GlobalColor.transparent)
        pixmap_active.setDevicePixelRatio(4.0)
        painter = QPainter(pixmap_active)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(Qt.GlobalColor.white, 1.5))
        painter.setBrush(Qt.GlobalColor.white)
        painter.drawEllipse(QRectF(1.0, 1.0, 30.0, 30.0))
        painter.setPen(QPen(QColor(REQUIRED_COLOR), 3.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        painter.drawLine(QPointF(9.0, 16.0), QPointF(14.0, 21.0))
        painter.drawLine(QPointF(14.0, 21.0), QPointF(22.0, 10.0))
        painter.end()

        return pixmap_inactive, pixmap_active

    def create_exclude_card_icon(self) -> QPixmap:
        pixmap = QPixmap(96, 96)
        pixmap.fill(Qt.GlobalColor.transparent)
        pixmap.setDevicePixelRatio(4.0)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QColor(EXCLUDE_COLOR))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(QRectF(1.0, 1.0, 22.0, 22.0))
        painter.setPen(QPen(Qt.GlobalColor.white, 3.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawLine(QPointF(6.0, 12.0), QPointF(18.0, 12.0))
        painter.end()
        return pixmap

    def create_required_card_icon(self) -> QPixmap:
        pixmap = QPixmap(96, 96)
        pixmap.fill(Qt.GlobalColor.transparent)
        pixmap.setDevicePixelRatio(4.0)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor(REQUIRED_COLOR), 2.0))
        painter.setBrush(Qt.GlobalColor.white)
        painter.drawEllipse(QRectF(1.0, 1.0, 22.0, 22.0))
        painter.setPen(QPen(QColor(REQUIRED_COLOR), 3.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        painter.drawLine(QPointF(6.0, 12.0), QPointF(10.0, 16.0))
        painter.drawLine(QPointF(10.0, 16.0), QPointF(18.0, 7.0))
        painter.end()
        return pixmap

    def create_play_icon(self) -> QIcon:
        pixmap = QPixmap(64, 64)
        pixmap.fill(Qt.GlobalColor.transparent)
        pixmap.setDevicePixelRatio(4.0)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QColor("#142033"))
        painter.setPen(Qt.PenStyle.NoPen)
        points = [QPointF(4.0, 3.0), QPointF(4.0, 13.0), QPointF(13.0, 8.0)]
        painter.drawPolygon(points)
        painter.end()
        return QIcon(pixmap)

    def create_pause_icon(self) -> QIcon:
        pixmap = QPixmap(64, 64)
        pixmap.fill(Qt.GlobalColor.transparent)
        pixmap.setDevicePixelRatio(4.0)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QColor("#142033"))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRect(QRectF(4.0, 3.0, 3.0, 10.0))
        painter.drawRect(QRectF(9.0, 3.0, 3.0, 10.0))
        painter.end()
        return QIcon(pixmap)

    def create_fullscreen_icon(self) -> QIcon:
        pixmap = QPixmap(64, 64)
        pixmap.fill(Qt.GlobalColor.transparent)
        pixmap.setDevicePixelRatio(4.0)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor("#142033"), 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.FlatCap, Qt.PenJoinStyle.MiterJoin))
        painter.drawLine(QPointF(3.0, 6.0), QPointF(3.0, 3.0))
        painter.drawLine(QPointF(3.0, 3.0), QPointF(6.0, 3.0))
        painter.drawLine(QPointF(10.0, 3.0), QPointF(13.0, 3.0))
        painter.drawLine(QPointF(13.0, 3.0), QPointF(13.0, 6.0))
        painter.drawLine(QPointF(3.0, 10.0), QPointF(3.0, 13.0))
        painter.drawLine(QPointF(3.0, 13.0), QPointF(6.0, 13.0))
        painter.drawLine(QPointF(10.0, 13.0), QPointF(13.0, 13.0))
        painter.drawLine(QPointF(13.0, 13.0), QPointF(13.0, 10.0))
        painter.end()
        return QIcon(pixmap)

    def __init__(
        self, media: MediaItem, media_path: str, parent: QWidget | None = None, proxy_path: str | None = None,
    ) -> None:
        super().__init__(parent)
        self.media = media
        self.original_media_path = Path(media_path)
        self.proxy_path = Path(proxy_path) if proxy_path else None
        self.proxy_partial_path = (
            self.proxy_path.with_name(f"{self.proxy_path.stem}.partial.mp4") if self.proxy_path else None
        )
        self.proxy_process: QProcess | None = None
        self.proxy_progress_buffer = ""
        self.duration_ms = max(1, round(media.duration * 1000))
        self.draft = [replace(selection) for selection in media.selections]
        self.selected_index = -1
        self._preview_ready = False
        self._hover_warming = False
        self._pending_hover_position: int | None = None
        self._normal_geometry = None
        self._fullscreen_compact = False
        self.hover_seek_timer = QTimer(self)
        self.hover_seek_timer.setSingleShot(True)
        self.hover_seek_timer.setInterval(25)
        self.hover_seek_timer.timeout.connect(self.perform_hover_seek)
        self.setWindowTitle(f"Preview / Edit - {media.original_name}")
        self.resize(1240, 780)

        self.video = PreviewVideoWidget()
        self.video.setMinimumHeight(260)
        self.audio = QAudioOutput(self)
        self.audio.setVolume(0.75)
        self.player = QMediaPlayer(self)
        self.player.setAudioOutput(self.audio)
        self.player.setVideoOutput(self.video)

        self.play_icon = self.create_play_icon()
        self.pause_icon = self.create_pause_icon()
        self.fullscreen_icon = self.create_fullscreen_icon()

        self.play_button = QPushButton()
        self.play_button.setObjectName("playButton")
        self.play_button.setIcon(self.play_icon)
        self.play_button.setIconSize(QSize(16, 16))
        self.play_button.clicked.connect(self.toggle_playback)

        self.time_label = QLabel()

        self.fullscreen_button = QPushButton("Full Screen")
        self.fullscreen_button.setObjectName("fullscreenButton")
        self.fullscreen_button.setIcon(self.fullscreen_icon)
        self.fullscreen_button.setIconSize(QSize(14, 14))
        self.fullscreen_button.clicked.connect(self.toggle_fullscreen)

        self.controls_layout = QHBoxLayout()
        self.controls_layout.addWidget(self.play_button)
        self.controls_layout.addStretch(1)
        self.controls_layout.addWidget(self.time_label)
        self.controls_layout.addStretch(1)
        self.controls_layout.addWidget(self.fullscreen_button)

        self.timeline = SelectionTimeline(self.duration_ms)
        self.timeline.setToolTip("Hover to preview a frame. Choose a paint mode, then drag to mark a range.")

        self.selection_mode_panel = self.build_selection_mode_panel()

        self.exclude_tool.clicked.connect(lambda: self.set_selection_tool(SelectionType.EXCLUDE))
        self.required_tool.clicked.connect(lambda: self.set_selection_tool(SelectionType.REQUIRED))
        self.timeline.toolChanged.connect(self.update_selection_mode_ui)
        self.timeline.selectionChanged.connect(self.select_selection)
        self.timeline.rangeCreated.connect(self.create_selection)
        self.timeline.rangeEdited.connect(self.edit_range)
        self.timeline.positionPreviewed.connect(self.preview_position)

        self.exclude_table_icon = self.create_exclude_table_icon()
        self.required_table_icon = self.create_required_table_icon()

        self.selection_table = QTableWidget(0, 5)
        self.selection_table.setObjectName("selectionTable")
        self.selection_table.setHorizontalHeaderLabels(["#", "Type", "Start", "End", "Duration"])
        self.selection_table.verticalHeader().setVisible(False)
        self.selection_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.selection_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.selection_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)

        header = self.selection_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.selection_table.setColumnWidth(0, 50)
        self.selection_table.setColumnWidth(1, 150)

        selection_table_height = (
            self.selection_table.horizontalHeader().sizeHint().height()
            + self.selection_table.verticalHeader().defaultSectionSize() * 4
            + self.selection_table.frameWidth() * 2
            + 4
        )
        self.selection_table.setMinimumHeight(selection_table_height)
        self.selection_table.setMaximumHeight(selection_table_height)
        self.selection_table.itemSelectionChanged.connect(self.table_selection_changed)
        self.selection_table.installEventFilter(self)

        self.warning = QLabel()
        self.warning.setStyleSheet("color: #b3261e;")
        self.warning.setWordWrap(True)
        self.proxy_status = QLabel()
        self.proxy_status.setStyleSheet("color: #66758A;")
        self.proxy_status.setWordWrap(False)
        self.proxy_status.setMaximumHeight(22)
        self.proxy_progress = QProgressBar()
        self.proxy_progress.setRange(0, 100)
        self.proxy_progress.setValue(0)
        self.proxy_progress.setFormat("Preparing fast preview… %p%")
        self.proxy_progress.setMaximumHeight(18)
        self.proxy_progress.setVisible(False)

        self.button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        save_btn = self.button_box.button(QDialogButtonBox.StandardButton.Save)
        if save_btn:
            save_btn.setObjectName("saveButton")
        cancel_btn = self.button_box.button(QDialogButtonBox.StandardButton.Cancel)
        if cancel_btn:
            cancel_btn.setObjectName("cancelButton")
        self.button_box.accepted.connect(self.save_and_accept)
        self.button_box.rejected.connect(self.reject)

        self.setStyleSheet(PREVIEW_DIALOG_STYLES)

        self.video_container = AspectWidget(self.video, 16.0 / 9.0)
        self.video_container.on_resize_callback = self.adjust_controls_margins

        self.preview_container = QWidget()
        right_layout = QVBoxLayout(self.preview_container)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(6)
        right_layout.addWidget(self.video_container, 1)
        right_layout.addLayout(self.controls_layout)

        self.top_split = QHBoxLayout()
        self.top_split.setSpacing(10)
        self.top_split.addWidget(self.selection_mode_panel, 1)
        self.top_split.addWidget(self.preview_container, 1)

        legend_row = QHBoxLayout()
        legend_row.setContentsMargins(14, 0, 14, 0)
        legend_row.setSpacing(16)

        red_dot = QLabel(f'<span style="color:{EXCLUDE_COLOR};">■</span>  Red = Excluded from final video')
        red_dot.setTextFormat(Qt.TextFormat.RichText)
        red_dot.setStyleSheet("font-size: 8.5pt; color: #526173;")

        green_dot = QLabel(f'<span style="color:{REQUIRED_COLOR};">■</span>  Green = Must keep in final video')
        green_dot.setTextFormat(Qt.TextFormat.RichText)
        green_dot.setStyleSheet("font-size: 8.5pt; color: #526173;")

        legend_row.addWidget(red_dot)
        legend_row.addWidget(green_dot)
        legend_row.addStretch()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)
        layout.addLayout(self.top_split)
        layout.addWidget(self.timeline)
        layout.addLayout(legend_row)
        layout.addWidget(self.selection_table, 1)
        layout.addWidget(self.proxy_status)
        layout.addWidget(self.proxy_progress)
        layout.addWidget(self.warning)
        layout.addWidget(self.button_box)

        self.player.positionChanged.connect(self.position_changed)
        self.player.playbackStateChanged.connect(self.playback_state_changed)
        self.video.videoSink().videoFrameChanged.connect(self.video_frame_changed)
        self.player.errorOccurred.connect(self.playback_error)
        cached_proxy = (
            self.proxy_path is not None
            and preview_proxy_is_current(self.original_media_path, self.proxy_path)
        )
        active_path = self.proxy_path if cached_proxy else self.original_media_path
        self.player.setSource(QUrl.fromLocalFile(str(active_path)))
        if cached_proxy:
            self.proxy_status.setText("Using optimized low-resolution preview.")
        elif self.proxy_path is not None:
            self.start_proxy_build()
        self.escape_shortcut = QShortcut(QKeySequence(Qt.Key.Key_Escape), self)
        self.escape_shortcut.activated.connect(self.exit_fullscreen)
        self.delete_shortcut = QShortcut(QKeySequence(Qt.Key.Key_Delete), self)
        self.delete_shortcut.activated.connect(self.delete_selection)
        self.backspace_shortcut = QShortcut(QKeySequence(Qt.Key.Key_Backspace), self)
        self.backspace_shortcut.activated.connect(self.delete_selection)

        self.exclude_shortcut = QShortcut(QKeySequence("E"), self)
        self.exclude_shortcut.activated.connect(lambda: self.set_selection_tool(SelectionType.EXCLUDE))
        self.required_shortcut = QShortcut(QKeySequence("R"), self)
        self.required_shortcut.activated.connect(lambda: self.set_selection_tool(SelectionType.REQUIRED))

        self.refresh_selections()
        self.position_changed(0)
        self.set_selection_tool(SelectionType.EXCLUDE)

    def create_shortcut_badge(self, key: str, action: str) -> QWidget:
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        
        key_label = QLabel(key)
        key_label.setStyleSheet("""
            QLabel {
                border: 1px solid #CDD8DC;
                border-radius: 4px;
                background: #FFFFFF;
                color: #526173;
                padding: 2px 6px;
                font-size: 8.5pt;
                font-weight: bold;
            }
        """)
        
        action_label = QLabel(action)
        action_label.setStyleSheet("color: #526173; font-size: 9pt; font-weight: 500;")
        
        layout.addWidget(key_label, alignment=Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(action_label, alignment=Qt.AlignmentFlag.AlignVCenter)
        return container

    def build_selection_mode_panel(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("selectionModePanel")

        self.selection_mode_outer = QVBoxLayout(panel)
        self.selection_mode_outer.setContentsMargins(16, 16, 16, 16)
        self.selection_mode_outer.setSpacing(12)

        # Top row: title + subtitle on the left, shortcut badges on the right
        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        
        # Left side: Title + Subtitle
        title_container = QWidget()
        title_layout = QVBoxLayout(title_container)
        title_layout.setContentsMargins(0, 0, 0, 0)
        title_layout.setSpacing(2)
        
        self.selection_mode_title_label = QLabel("Selection Mode")
        self.selection_mode_title_label.setStyleSheet("font-size: 16pt; font-weight: 800; color: #142033;")
        
        self.selection_mode_subtitle_label = QLabel("Paint on timeline")
        self.selection_mode_subtitle_label.setStyleSheet("font-size: 9.5pt; color: #526173; font-weight: 500;")
        
        title_layout.addWidget(self.selection_mode_title_label)
        title_layout.addWidget(self.selection_mode_subtitle_label)
        
        # Right side: Shortcut badges
        badge_layout = QHBoxLayout()
        badge_layout.setContentsMargins(0, 0, 0, 0)
        badge_layout.setSpacing(12)
        self.selection_mode_shortcuts = [
            self.create_shortcut_badge("E", "Exclude"),
            self.create_shortcut_badge("R", "Required"),
            self.create_shortcut_badge("Delete", "Remove"),
        ]
        for shortcut in self.selection_mode_shortcuts:
            badge_layout.addWidget(shortcut, alignment=Qt.AlignmentFlag.AlignVCenter)
        
        top_row.addWidget(title_container)
        top_row.addStretch(1)
        top_row.addLayout(badge_layout)
        
        self.selection_mode_outer.addLayout(top_row)

        # Timeline help text below title row
        self.timeline_help_label = QLabel(
            "ⓘ  Drag left or right on the timeline to paint segments."
        )
        self.timeline_help_label.setObjectName("timelineHelpLabel")
        self.timeline_help_label.setStyleSheet("color: #526173; font-size: 9.5pt;")
        self.timeline_help_label.setWordWrap(True)
        self.selection_mode_outer.addWidget(self.timeline_help_label)
        self.selection_mode_stretch = self.selection_mode_outer.addStretch(1)

        self.selection_mode_button_row = QHBoxLayout()
        self.selection_mode_button_row.setSpacing(24)

        # Generate Exclude and Required button icons
        self.exclude_btn_inactive, self.exclude_btn_active = self.create_exclude_button_icons()
        self.required_btn_inactive, self.required_btn_active = self.create_required_button_icons()
        
        # Current Mode Card status icons
        self.exclude_card_icon_pixmap = self.create_exclude_card_icon()
        self.required_card_icon_pixmap = self.create_required_card_icon()

        # Exclude Mode Button setup
        self.exclude_tool = QPushButton()
        self.exclude_tool.setObjectName("excludeModeButton")
        self.exclude_tool.setCheckable(True)
        self.exclude_tool.setMinimumHeight(68)
        self.exclude_tool.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.exclude_tool.setAccessibleName("Exclude mode")
        self.exclude_tool.setAccessibleDescription("Remove painted timeline sections from the final video.")

        exclude_layout = QHBoxLayout(self.exclude_tool)
        exclude_layout.setContentsMargins(16, 8, 16, 8)
        exclude_layout.setSpacing(12)

        self.exclude_icon_label = QLabel()
        self.exclude_icon_label.setFixedSize(32, 32)
        self.exclude_icon_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        exclude_text_layout = QVBoxLayout()
        exclude_text_layout.setContentsMargins(0, 0, 0, 0)
        exclude_text_layout.setSpacing(1)

        self.exclude_title_label = QLabel("Exclude")
        self.exclude_title_label.setObjectName("excludeTitleLabel")
        self.exclude_title_label.setStyleSheet("font-weight: 800; font-size: 11.5pt; background: transparent;")
        self.exclude_title_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        self.exclude_subtitle_label = QLabel("Remove from final video")
        self.exclude_subtitle_label.setObjectName("excludeSubtitleLabel")
        self.exclude_subtitle_label.setStyleSheet("font-weight: 400; font-size: 9.5pt; background: transparent;")
        self.exclude_subtitle_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        exclude_text_layout.addWidget(self.exclude_title_label)
        exclude_text_layout.addWidget(self.exclude_subtitle_label)

        exclude_layout.addWidget(self.exclude_icon_label)
        exclude_layout.addLayout(exclude_text_layout)
        exclude_layout.addStretch()

        # Required Mode Button setup
        self.required_tool = QPushButton()
        self.required_tool.setObjectName("requiredModeButton")
        self.required_tool.setCheckable(True)
        self.required_tool.setMinimumHeight(68)
        self.required_tool.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.required_tool.setAccessibleName("Required mode")
        self.required_tool.setAccessibleDescription("Keep painted timeline sections in the final video.")

        required_layout = QHBoxLayout(self.required_tool)
        required_layout.setContentsMargins(16, 8, 16, 8)
        required_layout.setSpacing(12)

        self.required_icon_label = QLabel()
        self.required_icon_label.setFixedSize(32, 32)
        self.required_icon_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        required_text_layout = QVBoxLayout()
        required_text_layout.setContentsMargins(0, 0, 0, 0)
        required_text_layout.setSpacing(1)

        self.required_title_label = QLabel("Required")
        self.required_title_label.setObjectName("requiredTitleLabel")
        self.required_title_label.setStyleSheet("font-weight: 800; font-size: 11.5pt; background: transparent;")
        self.required_title_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        self.required_subtitle_label = QLabel("Keep in final video")
        self.required_subtitle_label.setObjectName("requiredSubtitleLabel")
        self.required_subtitle_label.setStyleSheet("font-weight: 400; font-size: 9.5pt; background: transparent;")
        self.required_subtitle_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        required_text_layout.addWidget(self.required_title_label)
        required_text_layout.addWidget(self.required_subtitle_label)

        required_layout.addWidget(self.required_icon_label)
        required_layout.addLayout(required_text_layout)
        required_layout.addStretch()

        tools = QButtonGroup(self)
        tools.setExclusive(True)
        tools.addButton(self.exclude_tool)
        tools.addButton(self.required_tool)

        # Current Mode Card
        self.current_mode_card = QFrame()
        self.current_mode_card.setObjectName("currentModeCard")
        current_layout = QHBoxLayout(self.current_mode_card)
        current_layout.setContentsMargins(12, 10, 12, 10)
        current_layout.setSpacing(12)

        self.current_mode_icon = QLabel()
        self.current_mode_icon.setFixedSize(24, 24)

        text_layout = QVBoxLayout()
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(2)

        self.current_mode_title = QLabel()
        self.current_mode_title.setObjectName("currentModeTitle")
        self.current_mode_title.setTextFormat(Qt.TextFormat.RichText)

        self.current_mode_instruction = QLabel()
        self.current_mode_instruction.setObjectName("currentModeInstruction")
        self.current_mode_instruction.setWordWrap(True)

        text_layout.addWidget(self.current_mode_title)
        text_layout.addWidget(self.current_mode_instruction)

        current_layout.addWidget(self.current_mode_icon)
        current_layout.addLayout(text_layout, 1)

        self.selection_mode_button_row.addWidget(self.exclude_tool)
        self.selection_mode_button_row.addWidget(self.required_tool)

        self.selection_mode_outer.addLayout(self.selection_mode_button_row)
        self.selection_mode_outer.addWidget(self.current_mode_card)

        return panel

    def adjust_controls_margins(self, x_offset: int, width: int) -> None:
        self.controls_layout.setContentsMargins(x_offset, 0, x_offset, 0)

    def set_selection_tool(self, selection_type: SelectionType) -> None:
        self.timeline.set_tool(selection_type)
        self.update_selection_mode_ui(selection_type)

    def update_selection_mode_ui(self, selection_type: SelectionType | None = None) -> None:
        selection_type = selection_type or self.timeline.tool

        exclude_active = selection_type is SelectionType.EXCLUDE
        required_active = selection_type is SelectionType.REQUIRED

        self.exclude_tool.setChecked(exclude_active)
        self.required_tool.setChecked(required_active)

        self.exclude_tool.setProperty("modeActive", "true" if exclude_active else "false")
        self.required_tool.setProperty("modeActive", "true" if required_active else "false")

        self._repolish(self.exclude_tool)
        self._repolish(self.required_tool)

        if exclude_active:
            self.exclude_icon_label.setPixmap(self.exclude_btn_active)
            self.exclude_title_label.setStyleSheet("font-weight: 800; font-size: 11.5pt; background: transparent; color: #FFFFFF;")
            self.exclude_subtitle_label.setStyleSheet("font-weight: 400; font-size: 9.5pt; background: transparent; color: #FFFFFF;")

            self.required_icon_label.setPixmap(self.required_btn_inactive)
            self.required_title_label.setStyleSheet("font-weight: 800; font-size: 11.5pt; background: transparent; color: #142033;")
            self.required_subtitle_label.setStyleSheet("font-weight: 400; font-size: 9.5pt; background: transparent; color: #526173;")

            self.current_mode_icon.setPixmap(self.exclude_card_icon_pixmap)
            self.current_mode_title.setText(
                f'Current mode: <span style="color:{EXCLUDE_COLOR}; font-weight:800;">EXCLUDE</span>'
            )
            self.current_mode_instruction.setText("Drag on the timeline to paint red excluded segments.")
            self.current_mode_card.setProperty("mode", "exclude")
        else:
            self.exclude_icon_label.setPixmap(self.exclude_btn_inactive)
            self.exclude_title_label.setStyleSheet("font-weight: 800; font-size: 11.5pt; background: transparent; color: #142033;")
            self.exclude_subtitle_label.setStyleSheet("font-weight: 400; font-size: 9.5pt; background: transparent; color: #526173;")

            self.required_icon_label.setPixmap(self.required_btn_active)
            self.required_title_label.setStyleSheet("font-weight: 800; font-size: 11.5pt; background: transparent; color: #FFFFFF;")
            self.required_subtitle_label.setStyleSheet("font-weight: 400; font-size: 9.5pt; background: transparent; color: #FFFFFF;")

            self.current_mode_icon.setPixmap(self.required_card_icon_pixmap)
            self.current_mode_title.setText(
                f'Current mode: <span style="color:{REQUIRED_COLOR}; font-weight:800;">REQUIRED</span>'
            )
            self.current_mode_instruction.setText("Drag on the timeline to paint green required segments.")
            self.current_mode_card.setProperty("mode", "required")

        self._repolish(self.current_mode_card)

    def _repolish(self, widget: QWidget) -> None:
        widget.style().unpolish(widget)
        widget.style().polish(widget)
        widget.update()

    def _set_fullscreen_layout(self, enabled: bool) -> None:
        """Switch between the editing layout and a video-first fullscreen layout."""
        self._fullscreen_compact = enabled

        self.top_split.removeWidget(self.selection_mode_panel)
        self.top_split.removeWidget(self.preview_container)
        if enabled:
            self.top_split.setDirection(QBoxLayout.Direction.TopToBottom)
            self.top_split.addWidget(self.preview_container, 1)
            self.top_split.addWidget(self.selection_mode_panel, 0)
        else:
            self.top_split.setDirection(QBoxLayout.Direction.LeftToRight)
            self.top_split.addWidget(self.selection_mode_panel, 1)
            self.top_split.addWidget(self.preview_container, 1)

        self.selection_mode_subtitle_label.setVisible(not enabled)
        self.timeline_help_label.setVisible(not enabled)
        self.current_mode_card.setVisible(not enabled)
        self.exclude_subtitle_label.setVisible(not enabled)
        self.required_subtitle_label.setVisible(not enabled)

        margins = (14, 10, 14, 10) if enabled else (16, 16, 16, 16)
        self.selection_mode_outer.setContentsMargins(*margins)
        self.selection_mode_outer.setSpacing(6 if enabled else 12)
        self.selection_mode_button_row.setSpacing(10 if enabled else 24)
        self.selection_mode_panel.setMaximumHeight(108 if enabled else 16_777_215)

        for button in (self.exclude_tool, self.required_tool):
            button.setMinimumHeight(44 if enabled else 68)
            button.setMaximumHeight(44 if enabled else 16_777_215)
            button.setMaximumWidth(220 if enabled else 16_777_215)

        self.selection_mode_title_label.setStyleSheet(
            f"font-size: {'12pt' if enabled else '16pt'}; font-weight: 800; color: #142033;"
        )
        self.top_split.invalidate()
        self.selection_mode_outer.invalidate()

    def exit_fullscreen(self) -> None:
        if not self.isFullScreen():
            return
        self.showNormal()
        if self._normal_geometry is not None:
            self.setGeometry(self._normal_geometry)
        self._set_fullscreen_layout(False)
        self.selection_table.setVisible(True)
        self.button_box.setVisible(True)
        self.proxy_status.setVisible(bool(self.proxy_status.text()))
        self.proxy_progress.setVisible(self.proxy_process is not None)
        self.warning.setVisible(bool(self.warning.text()))
        self.fullscreen_button.setText("Full Screen")

    def toggle_fullscreen(self) -> None:
        if self.isFullScreen():
            self.exit_fullscreen()
            return
        self._normal_geometry = self.geometry()
        for widget in (
            self.selection_table, self.proxy_status, self.proxy_progress, self.warning, self.button_box,
        ):
            widget.setVisible(False)
        self._set_fullscreen_layout(True)
        self.fullscreen_button.setText("Exit Full Screen")
        self.showFullScreen()

    def eventFilter(self, watched, event) -> bool:  # noqa: N802 - Qt API
        if (
            watched is self.selection_table
            and event.type() == QEvent.Type.KeyPress
            and event.key() in {Qt.Key.Key_Delete, Qt.Key.Key_Backspace}
        ):
            self.delete_selection()
            return True
        return super().eventFilter(watched, event)

    def toggle_playback(self) -> None:
        self.hover_seek_timer.stop()
        if self._hover_warming:
            self._hover_warming = False
            self._pending_hover_position = None
            self.audio.setMuted(False)
            self.player.play()
            return
        self._pending_hover_position = None
        if self.player.playbackState() is QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def playback_state_changed(self, state: QMediaPlayer.PlaybackState) -> None:
        if state is QMediaPlayer.PlaybackState.PlayingState:
            self.play_button.setIcon(self.pause_icon)
        else:
            self.play_button.setIcon(self.play_icon)

    def position_changed(self, position: int) -> None:
        if self._hover_warming and self._pending_hover_position is not None:
            position = self._pending_hover_position
        corrected_position = position
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            corrected_position = max(0, position - PLAYBACK_LATENCY_MS)
        corrected_position = max(0, min(corrected_position, self.duration_ms))
        self.timeline.set_playhead(corrected_position)
        frame = min(max(1, round(corrected_position * self.media.fps / 1000) + 1), max(1, round(self.media.duration * self.media.fps)))
        self.time_label.setText(f"{format_timecode(corrected_position)} / {format_timecode(self.duration_ms)}  |  Frame {frame}")

    def preview_position(self, position: int) -> None:
        position = max(0, min(position, self.duration_ms))
        self._pending_hover_position = position
        self.timeline.set_playhead(position)
        if not self.hover_seek_timer.isActive():
            self.hover_seek_timer.start()

    def perform_hover_seek(self) -> None:
        if self._pending_hover_position is None:
            return
        position = self._pending_hover_position
        if self.player.playbackState() is QMediaPlayer.PlaybackState.PlayingState:
            if not self._hover_warming:
                self.player.pause()
        self.player.setPosition(position)
        if not self._preview_ready and not self._hover_warming:
            # Some Windows media backends do not decode a seeked frame until the
            # playback graph has started once. Warm it silently, then pause on
            # the first decoded frame and re-apply the latest hover seek.
            self._hover_warming = True
            self.audio.setMuted(True)
            self.player.play()

    def video_frame_changed(self, frame) -> None:
        if not frame.isValid():
            return
        self._preview_ready = True
        if self._hover_warming:
            QTimer.singleShot(0, self.finish_hover_warmup)

    def finish_hover_warmup(self) -> None:
        if not self._hover_warming:
            return
        self._hover_warming = False
        try:
            self.player.pause()
            self.audio.setMuted(False)
        except RuntimeError:
            # A queued frame callback can arrive while the preview dialog is
            # being destroyed and its multimedia children are already gone.
            return
        self.apply_pending_hover()
        # Repeating the paused seek after the state transition makes WMF render
        # the requested frame instead of leaving its initial frame on screen.
        QTimer.singleShot(30, self.apply_pending_hover)

    def apply_pending_hover(self) -> None:
        if self._pending_hover_position is None:
            return
        position = self._pending_hover_position
        try:
            self.player.setPosition(position)
        except RuntimeError:
            return
        self.position_changed(position)

    def playback_error(self, *_args) -> None:
        self._hover_warming = False
        self.audio.setMuted(False)
        self.show_warning(f"Playback error: {self.player.errorString()}")

    def start_proxy_build(self) -> None:
        if (
            self.proxy_path is None or self.proxy_partial_path is None
            or not self.original_media_path.is_file() or self.proxy_process is not None
        ):
            return
        self.proxy_path.parent.mkdir(parents=True, exist_ok=True)
        self.proxy_partial_path.unlink(missing_ok=True)
        process = QProcess(self)
        process.setProgram("ffmpeg")
        process.setArguments(preview_proxy_arguments(self.original_media_path, self.proxy_partial_path))
        process.setProcessChannelMode(QProcess.ProcessChannelMode.SeparateChannels)
        process.readyReadStandardOutput.connect(self.read_proxy_progress)
        process.finished.connect(self.proxy_build_finished)
        process.errorOccurred.connect(self.proxy_build_error)
        self.proxy_process = process
        self.proxy_progress_buffer = ""
        self.proxy_progress.setValue(0)
        self.proxy_progress.setFormat("Preparing fast preview… %p%")
        self.proxy_progress.setVisible(True)
        self.proxy_status.setText("Building a fast low-resolution preview in the background…")
        process.start()

    def read_proxy_progress(self) -> None:
        if self.proxy_process is None:
            return
        self.proxy_progress_buffer += bytes(self.proxy_process.readAllStandardOutput()).decode("utf-8", errors="replace")
        lines = self.proxy_progress_buffer.split("\n")
        self.proxy_progress_buffer = lines.pop()
        for raw_line in lines:
            line = raw_line.strip()
            if line == "progress=end":
                self.proxy_progress.setValue(100)
                continue
            if not line.startswith(("out_time_us=", "out_time_ms=")):
                continue
            try:
                elapsed_seconds = int(line.split("=", 1)[1]) / 1_000_000
            except ValueError:
                continue
            percent = round(min(100.0, elapsed_seconds / max(self.media.duration, 0.001) * 100))
            self.proxy_progress.setValue(percent)

    def proxy_build_finished(self, exit_code: int, exit_status: QProcess.ExitStatus) -> None:
        process = self.proxy_process
        self.read_proxy_progress()
        self.proxy_process = None
        if process is None or self.proxy_path is None or self.proxy_partial_path is None:
            return
        output = bytes(process.readAllStandardError()).decode("utf-8", errors="replace").strip()
        if (
            exit_code != 0 or exit_status is not QProcess.ExitStatus.NormalExit
            or not self.proxy_partial_path.is_file() or self.proxy_partial_path.stat().st_size == 0
        ):
            self.proxy_partial_path.unlink(missing_ok=True)
            self.proxy_status.setText("Fast preview could not be created; using the original video.")
            self.proxy_progress.setVisible(False)
            if output:
                self.proxy_status.setToolTip(output[-2000:])
            return
        self.proxy_partial_path.replace(self.proxy_path)
        self.proxy_status.setText("Fast low-resolution preview ready.")
        self.proxy_progress.setValue(100)
        self.proxy_progress.setFormat("Fast preview ready")
        QTimer.singleShot(1200, self.proxy_progress.hide)
        self.switch_to_proxy()

    def proxy_build_error(self, error: QProcess.ProcessError) -> None:
        if error is not QProcess.ProcessError.FailedToStart:
            return
        self.proxy_process = None
        if self.proxy_partial_path is not None:
            self.proxy_partial_path.unlink(missing_ok=True)
        self.proxy_status.setText("FFmpeg could not start; using the original video for preview.")
        self.proxy_progress.setVisible(False)

    def switch_to_proxy(self) -> None:
        if self.proxy_path is None or not self.proxy_path.is_file():
            return
        position = self._pending_hover_position if self._pending_hover_position is not None else self.player.position()
        was_playing = self.player.playbackState() is QMediaPlayer.PlaybackState.PlayingState
        self.player.stop()
        self._preview_ready = False
        self._hover_warming = False
        self.audio.setMuted(False)
        self.player.setSource(QUrl.fromLocalFile(str(self.proxy_path)))
        self.show_warning("")
        if was_playing:
            self.player.setPosition(position)
            self.player.play()
        else:
            self.preview_position(position)

    def show_warning(self, message: str) -> None:
        self.warning.setText(message)

    def _validated(self, selections: list[ClipSelection]) -> list[ClipSelection] | None:
        try:
            return validate_clip_selections(selections, self.media.duration)
        except ValueError as exc:
            self.show_warning(str(exc))
            return None

    def create_selection(self, selection_type: SelectionType, start_ms: int, end_ms: int) -> None:
        candidate = [*self.draft, ClipSelection(selection_type, start_ms, end_ms)]
        validated = self._validated(candidate)
        if validated is None:
            return
        created = candidate[-1]
        self.draft = validated
        self.selected_index = self.draft.index(created)
        self.show_warning("")
        self.refresh_selections()

    def edit_range(self, index: int, start_ms: int, end_ms: int) -> None:
        if not 0 <= index < len(self.draft):
            return
        candidate = [replace(selection) for selection in self.draft]
        candidate[index] = replace(candidate[index], start_ms=start_ms, end_ms=end_ms)
        edited = candidate[index]
        validated = self._validated(candidate)
        if validated is None:
            self.refresh_selections()
            return
        self.draft = validated
        self.selected_index = self.draft.index(edited)
        self.show_warning("")
        self.refresh_selections()

    def refresh_selections(self) -> None:
        self.selection_table.blockSignals(True)
        self.selection_table.setRowCount(len(self.draft))
        for row, selection in enumerate(self.draft):
            # Column 0: Index centered
            num_item = QTableWidgetItem(str(row + 1))
            num_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.selection_table.setItem(row, 0, num_item)

            # Column 1: Type (with icon + text)
            is_required = selection.type is SelectionType.REQUIRED
            type_text = "Required" if is_required else "Exclude"
            type_item = QTableWidgetItem(type_text)
            
            # Icon
            icon = self.required_table_icon if is_required else self.exclude_table_icon
            type_item.setIcon(icon)
            
            # Color
            color_str = REQUIRED_COLOR if is_required else EXCLUDE_COLOR
            type_item.setForeground(QColor(color_str))
            self.selection_table.setItem(row, 1, type_item)

            # Column 2-4: Start, End, Duration
            values = [
                format_timecode(selection.start_ms),
                format_timecode(selection.end_ms),
                format_timecode(selection.duration_ms),
            ]
            for column, value in enumerate(values, start=2):
                item = QTableWidgetItem(value)
                self.selection_table.setItem(row, column, item)

        if 0 <= self.selected_index < len(self.draft):
            self.selection_table.selectRow(self.selected_index)
        self.selection_table.blockSignals(False)
        self.timeline.set_selections(self.draft, self.selected_index)

    def table_selection_changed(self) -> None:
        self.select_selection(self.selection_table.currentRow())

    def select_selection(self, index: int) -> None:
        self.selected_index = index if 0 <= index < len(self.draft) else -1
        self.timeline.set_selections(self.draft, self.selected_index)
        self.selection_table.blockSignals(True)
        if self.selected_index >= 0:
            self.selection_table.selectRow(self.selected_index)
        else:
            self.selection_table.clearSelection()
        self.selection_table.blockSignals(False)

    def delete_selection(self) -> None:
        if not 0 <= self.selected_index < len(self.draft):
            return
        del self.draft[self.selected_index]
        self.selected_index = min(self.selected_index, len(self.draft) - 1)
        self.show_warning("")
        self.refresh_selections()

    def save_and_accept(self) -> None:
        validated = self._validated(self.draft)
        if validated is None:
            QMessageBox.warning(self, "Invalid selections", self.warning.text())
            return
        self.draft = validated
        self.media.selections = [replace(selection) for selection in self.draft]
        self.accept()

    def done(self, result: int) -> None:
        self.hover_seek_timer.stop()
        if self.proxy_process is not None:
            self.proxy_process.kill()
            self.proxy_process.waitForFinished(1000)
            self.proxy_process = None
        if self.proxy_partial_path is not None:
            self.proxy_partial_path.unlink(missing_ok=True)
        self.player.stop()
        self.video.setFullScreen(False)

    def showEvent(self, event) -> None:
        from PySide6.QtGui import QShowEvent
        super().showEvent(event)
        if not getattr(self, "_onboarding_triggered", False):
            self._onboarding_triggered = True
            from PySide6.QtCore import QTimer
            QTimer.singleShot(250, self.check_onboarding)

    def resizeEvent(self, event) -> None:
        from PySide6.QtGui import QResizeEvent
        super().resizeEvent(event)
        if hasattr(self, "onboarding_overlay") and self.onboarding_overlay:
            self.onboarding_overlay.setGeometry(self.rect())
        if hasattr(self, "video_placeholder") and self.video_placeholder and self.video_placeholder.isVisible():
            self.video_placeholder.setGeometry(self.video.geometry())

    def check_onboarding(self) -> None:
        from .onboarding import preview_onboarding_enabled
        if preview_onboarding_enabled():
            self.show_onboarding()

    def show_onboarding(self) -> None:
        if hasattr(self, "onboarding_overlay") and self.onboarding_overlay and self.onboarding_overlay.isVisible():
            return
            
        # Hide hardware-accelerated video widget to prevent Z-order occlusion issues on Windows.
        # Show a matching dark QFrame placeholder in its place.
        if not hasattr(self, "video_placeholder") or not self.video_placeholder:
            self.video_placeholder = QFrame(self.video_container)
            self.video_placeholder.setObjectName("videoPlaceholder")
            self.video_placeholder.setStyleSheet("background-color: #1A1A1A; border-radius: 4px;")
            self.video_placeholder.setGeometry(self.video.geometry())
            
        self.video_placeholder.setGeometry(self.video.geometry())
        self.video_placeholder.show()
        self.video.hide()

        from .onboarding import OnboardingOverlay
        if not hasattr(self, "onboarding_overlay") or not self.onboarding_overlay:
            self.onboarding_overlay = OnboardingOverlay(self, self.get_onboarding_steps(), "startup/show_preview_onboarding")
            self.onboarding_overlay.setGeometry(self.rect())
            self.onboarding_overlay.finished.connect(self._on_onboarding_finished)
        else:
            self.onboarding_overlay.steps = self.get_onboarding_steps()
        self.onboarding_overlay.show_onboarding()

    def _on_onboarding_finished(self) -> None:
        if hasattr(self, "video_placeholder") and self.video_placeholder:
            self.video_placeholder.hide()
        self.video.show()

    def get_onboarding_steps(self) -> list[dict]:
        from PySide6.QtCore import QRectF
        steps = [
            {
                "target": lambda dialog: QRectF(0, 0, dialog.width(), dialog.height()),
                "title": "Welcome to Preview & Edit",
                "description": "This tool allows you to select which segments of your drone footage you want to keep or remove for the final production. Let's take a quick tour!"
            }
        ]
        
        # Only show proxy building step if a preview build is currently underway
        # (i.e. not using a cached proxy)
        if not (self.proxy_path is not None and preview_proxy_is_current(self.original_media_path, self.proxy_path)):
            steps.append({
                "target": lambda dialog: dialog._get_proxy_section_rect(),
                "title": "Fast Low-Resolution Preview",
                "description": "When you first open a clip, the app generates a low-resolution preview in the background to ensure playback and editing are completely smooth. This process runs only once per video file."
            })
            
        steps.extend([
            {
                "target": lambda dialog: dialog._get_shortcuts_rect(),
                "title": "Keyboard Shortcuts",
                "description": "Quickly toggle tools using keyboard shortcuts: press 'E' for Exclude, 'R' for Required, and 'Delete' or 'Backspace' to remove a highlighted segment."
            },
            {
                "target": lambda dialog: dialog.exclude_tool,
                "title": "Exclude Tool",
                "description": "Select this tool to mark segments of the video that you want to remove from your final movie production."
            },
            {
                "target": lambda dialog: dialog.required_tool,
                "title": "Required Tool",
                "description": "Select this tool to mark segments that are absolutely essential to keep in your final movie production."
            },
            {
                "target": lambda dialog: dialog.timeline,
                "title": "Timeline Painter",
                "description": "Use your mouse to draw on the timeline: left-click and drag to paint Exclude (red) or Required (green) segments. You can also click and drag existing segments to move them, or drag their left/right edges to adjust their start and end points."
            },
            {
                "target": lambda dialog: dialog.selection_table,
                "title": "Selected Segments List",
                "description": "This table lists all the marked segments for the current clip. Double-click any row to jump directly to that point in the video, or select a row and press Delete to remove it."
            }
        ])
        return steps

    def _get_proxy_section_rect(self) -> QRectF:
        from PySide6.QtCore import QPoint, QRectF
        top_left = self.proxy_status.mapTo(self, QPoint(0, 0))
        bottom_right = self.proxy_progress.mapTo(self, QPoint(self.proxy_progress.width(), self.proxy_progress.height()))
        padding = 8
        return QRectF(
            top_left.x() - padding,
            top_left.y() - padding,
            bottom_right.x() - top_left.x() + 2 * padding,
            bottom_right.y() - top_left.y() + 2 * padding
        )

    def _get_shortcuts_rect(self) -> QRectF:
        from PySide6.QtCore import QPoint, QRectF
        if not hasattr(self, "selection_mode_shortcuts") or not self.selection_mode_shortcuts:
            return QRectF()
        first = self.selection_mode_shortcuts[0]
        last = self.selection_mode_shortcuts[-1]
        top_left = first.mapTo(self, QPoint(0, 0))
        bottom_right = last.mapTo(self, QPoint(last.width(), last.height()))
        padding = 8
        return QRectF(
            top_left.x() - padding,
            top_left.y() - padding,
            bottom_right.x() - top_left.x() + 2 * padding,
            bottom_right.y() - top_left.y() + 2 * padding
        )
