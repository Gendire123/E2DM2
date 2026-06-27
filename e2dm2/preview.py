from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QEvent, QProcess, QRectF, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QKeySequence, QMouseEvent, QPainter, QPen, QShortcut
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .models import (
    MAX_REQUIRED_SELECTION_MS,
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

    HANDLE_WIDTH = 7

    def __init__(self, duration_ms: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.duration_ms = max(1, duration_ms)
        self.selections: list[ClipSelection] = []
        self.selected_index = -1
        self.tool = SelectionType.EXCLUDE
        self._drag_mode: str | None = None
        self._drag_index = -1
        self._anchor_ms = 0
        self._preview_start: int | None = None
        self._preview_end: int | None = None
        self.playhead_ms = 0
        self.hover_ms: int | None = None
        self.setMinimumHeight(78)
        self.setMouseTracking(True)

    def set_selections(self, selections: list[ClipSelection], selected_index: int = -1) -> None:
        self.selections = [replace(selection) for selection in selections]
        self.selected_index = selected_index if 0 <= selected_index < len(selections) else -1
        self.update()

    def set_tool(self, selection_type: SelectionType) -> None:
        self.tool = selection_type

    def set_playhead(self, position_ms: int) -> None:
        self.playhead_ms = max(0, min(position_ms, self.duration_ms))
        self.update()

    def _track_rect(self) -> QRectF:
        return QRectF(10, 20, max(1, self.width() - 20), 34)

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
        painter.fillRect(rect, QColor("#d9dedb"))
        painter.setPen(QPen(QColor("#7c8981"), 1))
        for tick in range(11):
            x = rect.left() + rect.width() * tick / 10
            painter.drawLine(round(x), round(rect.top() - 5), round(x), round(rect.bottom() + 5))
        for index, selection in enumerate(self.selections):
            color = QColor("#2fa55d") if selection.type is SelectionType.REQUIRED else QColor("#d84a4a")
            color.setAlpha(205)
            selection_rect = QRectF(
                self._x_for_ms(selection.start_ms), rect.top(),
                max(2, self._x_for_ms(selection.end_ms) - self._x_for_ms(selection.start_ms)), rect.height(),
            )
            painter.fillRect(selection_rect, color)
            if index == self.selected_index:
                painter.setPen(QPen(QColor("#17231d"), 2))
                painter.drawRect(selection_rect)
                painter.fillRect(QRectF(selection_rect.left() - 2, rect.top(), 5, rect.height()), QColor("#fcfcfc"))
                painter.fillRect(QRectF(selection_rect.right() - 2, rect.top(), 5, rect.height()), QColor("#fcfcfc"))
        if self._preview_start is not None and self._preview_end is not None:
            start, end = sorted((self._preview_start, self._preview_end))
            color = QColor("#2fa55d") if self.tool is SelectionType.REQUIRED else QColor("#d84a4a")
            color.setAlpha(130)
            painter.fillRect(
                QRectF(self._x_for_ms(start), rect.top(), max(2, self._x_for_ms(end) - self._x_for_ms(start)), rect.height()),
                color,
            )
        playhead_x = self._x_for_ms(self.playhead_ms)
        painter.setPen(QPen(QColor("#1976d2"), 2))
        painter.drawLine(round(playhead_x), round(rect.top() - 4), round(playhead_x), round(rect.bottom() + 4))
        if self.hover_ms is not None:
            hover_x = self._x_for_ms(self.hover_ms)
            painter.setPen(QPen(QColor("#f2a900"), 1, Qt.PenStyle.DashLine))
            painter.drawLine(round(hover_x), round(rect.top() - 7), round(hover_x), round(rect.bottom() + 7))
            hover_label = format_timecode(self.hover_ms)
            label_width = painter.fontMetrics().horizontalAdvance(hover_label)
            label_x = max(10, min(self.width() - label_width - 10, round(hover_x - label_width / 2)))
            painter.setPen(QColor("#354039"))
            painter.drawText(label_x, round(rect.bottom() + 20), hover_label)
        painter.setPen(QColor("#354039"))
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
        selected = self._selection_at(x)
        if selected >= 0:
            self.selected_index = selected
            self.selectionChanged.emit(selected)
            selection = self.selections[selected]
            if abs(x - self._x_for_ms(selection.start_ms)) <= self.HANDLE_WIDTH:
                self._drag_mode = "start"
            elif abs(x - self._x_for_ms(selection.end_ms)) <= self.HANDLE_WIDTH:
                self._drag_mode = "end"
            else:
                self._drag_mode = None
            self._drag_index = selected
            self.update()
            return
        self.selected_index = -1
        self.selectionChanged.emit(-1)
        self._drag_mode = "create"
        self._anchor_ms = self._ms_for_x(x)
        self._preview_start = self._anchor_ms
        self._preview_end = self._anchor_ms
        self.update()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt API
        value = self._ms_for_x(event.position().x())
        self.hover_ms = value
        self.positionPreviewed.emit(value)
        if not self._drag_mode:
            self.update()
            return
        if self._drag_mode == "create":
            if self.tool is SelectionType.REQUIRED and abs(value - self._anchor_ms) > MAX_REQUIRED_SELECTION_MS:
                value = self._anchor_ms + (MAX_REQUIRED_SELECTION_MS if value > self._anchor_ms else -MAX_REQUIRED_SELECTION_MS)
            self._preview_end = value
        elif 0 <= self._drag_index < len(self.selections):
            selection = self.selections[self._drag_index]
            if selection.type is SelectionType.REQUIRED:
                if self._drag_mode == "start":
                    value = max(value, selection.end_ms - MAX_REQUIRED_SELECTION_MS)
                else:
                    value = min(value, selection.start_ms + MAX_REQUIRED_SELECTION_MS)
            self._preview_start = value if self._drag_mode == "start" else selection.start_ms
            self._preview_end = value if self._drag_mode == "end" else selection.end_ms
        self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt API
        if event.button() != Qt.MouseButton.LeftButton or not self._drag_mode:
            return
        value = self._ms_for_x(event.position().x())
        self.hover_ms = value
        self.positionPreviewed.emit(value)
        if self._drag_mode == "create":
            if self.tool is SelectionType.REQUIRED and abs(value - self._anchor_ms) > MAX_REQUIRED_SELECTION_MS:
                value = self._anchor_ms + (MAX_REQUIRED_SELECTION_MS if value > self._anchor_ms else -MAX_REQUIRED_SELECTION_MS)
            start, end = sorted((self._anchor_ms, value))
            if start != end:
                self.rangeCreated.emit(self.tool, start, end)
        elif 0 <= self._drag_index < len(self.selections):
            selection = self.selections[self._drag_index]
            if selection.type is SelectionType.REQUIRED:
                if self._drag_mode == "start":
                    value = max(value, selection.end_ms - MAX_REQUIRED_SELECTION_MS)
                else:
                    value = min(value, selection.start_ms + MAX_REQUIRED_SELECTION_MS)
            start = value if self._drag_mode == "start" else selection.start_ms
            end = value if self._drag_mode == "end" else selection.end_ms
            self.rangeEdited.emit(self._drag_index, start, end)
        self._drag_mode = None
        self._drag_index = -1
        self._preview_start = None
        self._preview_end = None
        self.update()

    def leaveEvent(self, event) -> None:  # noqa: N802 - Qt API
        self.hover_ms = None
        self.update()
        super().leaveEvent(event)


class PreviewVideoWidget(QVideoWidget):
    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt API
        if event.key() == Qt.Key.Key_Escape and self.isFullScreen():
            self.setFullScreen(False)
            event.accept()
            return
        super().keyPressEvent(event)


class ClipPreviewDialog(QDialog):
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
        self.hover_seek_timer = QTimer(self)
        self.hover_seek_timer.setSingleShot(True)
        self.hover_seek_timer.setInterval(25)
        self.hover_seek_timer.timeout.connect(self.perform_hover_seek)
        self.setWindowTitle(f"Preview / Edit - {media.original_name}")
        self.resize(1000, 620)

        self.video = PreviewVideoWidget()
        self.video.setMinimumHeight(200)
        self.audio = QAudioOutput(self)
        self.audio.setVolume(0.75)
        self.player = QMediaPlayer(self)
        self.player.setAudioOutput(self.audio)
        self.player.setVideoOutput(self.video)

        self.play_button = QPushButton("Play")
        self.play_button.clicked.connect(self.toggle_playback)
        self.time_label = QLabel()
        self.fullscreen_button = QPushButton("Full Screen")
        self.fullscreen_button.clicked.connect(self.toggle_fullscreen)
        controls = QHBoxLayout()
        controls.addWidget(self.play_button)
        controls.addStretch(1)
        controls.addWidget(self.time_label)
        controls.addWidget(self.fullscreen_button)

        self.exclude_tool = QPushButton("Red: Exclude")
        self.required_tool = QPushButton("Green: Required")
        self.exclude_tool.setCheckable(True)
        self.required_tool.setCheckable(True)
        self.exclude_tool.setChecked(True)
        tools = QButtonGroup(self)
        tools.setExclusive(True)
        tools.addButton(self.exclude_tool)
        tools.addButton(self.required_tool)
        self.timeline = SelectionTimeline(self.duration_ms)
        self.timeline.setToolTip("Hover to preview a frame. Choose Red or Green, then drag to mark a range.")
        self.exclude_tool.clicked.connect(lambda: self.timeline.set_tool(SelectionType.EXCLUDE))
        self.required_tool.clicked.connect(lambda: self.timeline.set_tool(SelectionType.REQUIRED))
        self.timeline.selectionChanged.connect(self.select_selection)
        self.timeline.rangeCreated.connect(self.create_selection)
        self.timeline.rangeEdited.connect(self.edit_range)
        self.timeline.positionPreviewed.connect(self.preview_position)
        tool_row = QHBoxLayout()
        tool_row.setSpacing(6)
        tool_row.addWidget(self.exclude_tool)
        tool_row.addWidget(self.required_tool)
        tool_row.addWidget(QLabel("Hover to preview • Drag to mark"))
        tool_row.addStretch()
        self.selection_table = QTableWidget(0, 4)
        self.selection_table.setHorizontalHeaderLabels(["Type", "Start", "End", "Duration"])
        self.selection_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.selection_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.selection_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.selection_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        selection_table_height = (
            self.selection_table.horizontalHeader().sizeHint().height()
            + self.selection_table.verticalHeader().defaultSectionSize() * 5
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
        self.proxy_status.setStyleSheet("color: #68716b;")
        self.proxy_status.setWordWrap(False)
        self.proxy_status.setMaximumHeight(22)
        self.proxy_progress = QProgressBar()
        self.proxy_progress.setRange(0, 100)
        self.proxy_progress.setValue(0)
        self.proxy_progress.setFormat("Preparing fast preview… %p%")
        self.proxy_progress.setMaximumHeight(18)
        self.proxy_progress.setVisible(False)
        self.button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        self.button_box.accepted.connect(self.save_and_accept)
        self.button_box.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)
        layout.addWidget(self.video, 1)
        layout.addLayout(controls)
        layout.addLayout(tool_row)
        layout.addWidget(self.timeline)
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
        self.refresh_selections()
        self.position_changed(0)

    def exit_fullscreen(self) -> None:
        if not self.isFullScreen():
            return
        self.showNormal()
        if self._normal_geometry is not None:
            self.setGeometry(self._normal_geometry)
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
        self.play_button.setText("Pause" if state is QMediaPlayer.PlaybackState.PlayingState else "Play")

    def position_changed(self, position: int) -> None:
        if self._hover_warming and self._pending_hover_position is not None:
            position = self._pending_hover_position
        position = max(0, min(position, self.duration_ms))
        self.timeline.set_playhead(position)
        frame = min(max(1, round(position * self.media.fps / 1000) + 1), max(1, round(self.media.duration * self.media.fps)))
        self.time_label.setText(f"{format_timecode(position)} / {format_timecode(self.duration_ms)}  |  Frame {frame}")

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
        self.player.pause()
        self.audio.setMuted(False)
        self.apply_pending_hover()
        # Repeating the paused seek after the state transition makes WMF render
        # the requested frame instead of leaving its initial frame on screen.
        QTimer.singleShot(30, self.apply_pending_hover)

    def apply_pending_hover(self) -> None:
        if self._pending_hover_position is None:
            return
        position = self._pending_hover_position
        self.player.setPosition(position)
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
            values = [
                "Required" if selection.type is SelectionType.REQUIRED else "Exclude",
                format_timecode(selection.start_ms), format_timecode(selection.end_ms),
                format_timecode(selection.duration_ms),
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column == 0:
                    item.setForeground(QColor("#208348") if selection.type is SelectionType.REQUIRED else QColor("#bd2f2f"))
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
        super().done(result)
