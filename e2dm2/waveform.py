from __future__ import annotations

import hashlib
import json
import logging
import math
import subprocess
import sys
from array import array
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject, QPointF, QRectF, QRunnable, Qt, Signal, Slot
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QSizePolicy, QWidget

from .catalog import default_project_root


LOGGER = logging.getLogger(__name__)
WAVEFORM_VERSION = 1
SAMPLE_RATE = 800
PEAKS_PER_SECOND = 25
_ACTIVE_WAVEFORM_TASKS: set["WaveformTask"] = set()


@dataclass(slots=True)
class WaveformData:
    peaks: list[float]
    peaks_per_second: float
    duration_seconds: float


def _cache_path(audio_path: Path) -> Path:
    stat = audio_path.stat()
    identity = f"{audio_path.resolve()}|{stat.st_size}|{stat.st_mtime_ns}|{WAVEFORM_VERSION}"
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()
    return default_project_root() / "Cache" / "waveforms" / f"{digest}.json"


def extract_waveform(audio_path: Path) -> WaveformData:
    audio_path = audio_path.resolve()
    if not audio_path.is_file():
        raise FileNotFoundError(f"Audio file not found: {audio_path}")
    cache_path = _cache_path(audio_path)
    if cache_path.exists():
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            data = WaveformData(
                peaks=[float(value) for value in cached["peaks"]],
                peaks_per_second=float(cached["peaks_per_second"]),
                duration_seconds=float(cached["duration_seconds"]),
            )
            LOGGER.debug("Loaded waveform cache: %s", cache_path)
            return data
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
            cache_path.unlink(missing_ok=True)

    LOGGER.info("Analyzing waveform: %s", audio_path)
    command = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-i", str(audio_path),
        "-vn", "-ac", "1", "-ar", str(SAMPLE_RATE), "-f", "s16le", "-acodec", "pcm_s16le", "pipe:1",
    ]
    result = subprocess.run(command, capture_output=True)
    if result.returncode != 0:
        error = result.stderr.decode("utf-8", errors="replace").strip()
        raise ValueError(f"Could not analyze waveform: {error or 'FFmpeg failed'}")
    samples = array("h")
    samples.frombytes(result.stdout)
    if sys.byteorder != "little":
        samples.byteswap()
    if not samples:
        raise ValueError("The audio file did not contain waveform samples.")

    samples_per_peak = max(1, round(SAMPLE_RATE / PEAKS_PER_SECOND))
    peaks = []
    for index in range(0, len(samples), samples_per_peak):
        block = samples[index:index + samples_per_peak]
        peaks.append(min(1.0, max(abs(value) for value in block) / 32768.0))
    data = WaveformData(peaks, SAMPLE_RATE / samples_per_peak, len(samples) / SAMPLE_RATE)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = cache_path.with_suffix(".json.partial")
    temporary.write_text(json.dumps({
        "version": WAVEFORM_VERSION,
        "peaks_per_second": data.peaks_per_second,
        "duration_seconds": data.duration_seconds,
        "peaks": [round(value, 5) for value in data.peaks],
    }), encoding="utf-8")
    temporary.replace(cache_path)
    LOGGER.info("Waveform ready: %.3f seconds, %d peaks", data.duration_seconds, len(data.peaks))
    return data


class WaveformTaskSignals(QObject):
    finished = Signal(str, object)
    failed = Signal(str, str)


class WaveformTask(QRunnable):
    def __init__(self, audio_path: Path) -> None:
        super().__init__()
        self.setAutoDelete(False)
        self.audio_path = audio_path.resolve()
        self.signals = WaveformTaskSignals()
        _ACTIVE_WAVEFORM_TASKS.add(self)

    @Slot()
    def run(self) -> None:
        try:
            self.signals.finished.emit(str(self.audio_path), extract_waveform(self.audio_path))
        except Exception as exc:
            LOGGER.exception("Waveform analysis failed: %s", self.audio_path)
            self.signals.failed.emit(str(self.audio_path), str(exc))
        finally:
            _ACTIVE_WAVEFORM_TASKS.discard(self)


class WaveformWidget(QWidget):
    timestamp_added = Signal(float)
    marker_selected = Signal(int)
    marker_moved = Signal(int, float)
    marker_remove_requested = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.data: WaveformData | None = None
        self.position_seconds = 0.0
        self.duration_seconds = 0.0
        self.window_seconds: float | None = 40.0
        self.markers: list[float] = []
        self.loading = False
        self.error = ""
        self.marker_editable = True
        self.hover_x: float | None = None
        self.selected_marker_index = -1
        self.drag_marker_index: int | None = None
        self.drag_time: float | None = None
        self.creating_marker = False
        self.playhead_fraction = 0.28
        self.setMinimumHeight(155)
        self.setMaximumHeight(220)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMouseTracking(True)
        self.setToolTip("Press and drag to place a cut timestamp")

    def set_loading(self) -> None:
        self.data = None
        self.error = ""
        self.loading = True
        self.update()

    def set_error(self, message: str) -> None:
        self.data = None
        self.loading = False
        self.error = message
        self.update()

    def set_waveform(self, data: WaveformData) -> None:
        self.data = data
        self.duration_seconds = data.duration_seconds
        self.loading = False
        self.error = ""
        self.update()

    def set_position(self, seconds: float) -> None:
        self.position_seconds = max(0.0, min(seconds, self.duration_seconds or seconds))
        self.update()

    def set_duration(self, milliseconds: int) -> None:
        if milliseconds > 0:
            self.duration_seconds = milliseconds / 1000
            self.update()

    def set_markers(self, markers: list[float]) -> None:
        selected_value = (
            self.markers[self.selected_marker_index]
            if 0 <= self.selected_marker_index < len(self.markers)
            else None
        )
        self.markers = list(markers)
        if selected_value is not None and self.markers:
            self.selected_marker_index = min(
                range(len(self.markers)), key=lambda index: abs(self.markers[index] - selected_value)
            )
        elif self.selected_marker_index >= len(self.markers):
            self.selected_marker_index = -1
        self.update()

    def select_marker(self, index: int) -> None:
        self.selected_marker_index = index if 0 <= index < len(self.markers) else -1
        self.update()

    def set_marker_editable(self, editable: bool) -> None:
        self.marker_editable = editable
        self.setCursor(Qt.CursorShape.CrossCursor if editable else Qt.CursorShape.ArrowCursor)
        self.setToolTip("Press and drag to place or move a cut timestamp" if editable else "Duplicate this built-in preset to edit cut timestamps")

    def set_window_seconds(self, seconds: float | None) -> None:
        self.window_seconds = seconds
        self.update()

    def visible_window(self) -> tuple[float, float]:
        duration = max(self.duration_seconds, 0.001)
        if self.window_seconds is None:
            return 0.0, duration
        window = min(self.window_seconds, duration)
        before = window * self.playhead_fraction
        return self.position_seconds - before, self.position_seconds + (window - before)

    def time_at_x(self, x: float) -> float:
        start, end = self.visible_window()
        value = start + max(0.0, min(x, self.width())) / max(self.width(), 1) * (end - start)
        return max(0.0, min(value, self.duration_seconds))

    def x_for_time(self, timestamp: float) -> float:
        start, end = self.visible_window()
        return (timestamp - start) / max(end - start, 0.001) * self.width()

    def marker_at_x(self, x: float, tolerance: float = 9.0) -> int:
        candidates = [
            (abs(self.x_for_time(timestamp) - x), index)
            for index, timestamp in enumerate(self.markers)
            if -tolerance <= self.x_for_time(timestamp) <= self.width() + tolerance
        ]
        if not candidates:
            return -1
        distance, index = min(candidates)
        return index if distance <= tolerance else -1

    def delete_rect(self) -> QRectF:
        if not self.marker_editable:
            return QRectF()
        if not 0 <= self.selected_marker_index < len(self.markers):
            return QRectF()
        timestamp = self.markers[self.selected_marker_index]
        if timestamp <= 0.000001:
            return QRectF()
        x = self.x_for_time(timestamp)
        if not 0 <= x <= self.width():
            return QRectF()
        return QRectF(x - 9, self.height() - 19, 18, 18)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.data:
            if self.marker_editable and self.delete_rect().contains(event.position()):
                index = self.selected_marker_index
                self.selected_marker_index = -1
                self.marker_remove_requested.emit(index)
                self.update()
                event.accept()
                return
            index = self.marker_at_x(event.position().x())
            if index >= 0:
                self.select_marker(index)
                self.marker_selected.emit(index)
                if self.marker_editable and self.markers[index] > 0.000001:
                    self.drag_marker_index = index
                    self.drag_time = self.markers[index]
            elif self.marker_editable:
                self.selected_marker_index = -1
                self.creating_marker = True
                self.drag_time = self.time_at_x(event.position().x())
                self.update()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        self.hover_x = event.position().x()
        if self.marker_editable and event.buttons() & Qt.MouseButton.LeftButton:
            if self.creating_marker or self.drag_marker_index is not None:
                self.drag_time = self.time_at_x(event.position().x())
                self.update()
                event.accept()
                return
        if self.delete_rect().contains(event.position()):
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        elif self.marker_at_x(event.position().x()) >= 0 and self.marker_editable:
            self.setCursor(Qt.CursorShape.SizeHorCursor)
        else:
            self.setCursor(Qt.CursorShape.CrossCursor if self.marker_editable else Qt.CursorShape.ArrowCursor)
        self.update()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.data and self.marker_editable:
            timestamp = round(self.drag_time if self.drag_time is not None else self.time_at_x(event.position().x()), 6)
            if self.creating_marker:
                self.timestamp_added.emit(timestamp)
            elif self.drag_marker_index is not None:
                original = self.markers[self.drag_marker_index]
                if abs(original - timestamp) >= 0.0005:
                    self.marker_moved.emit(self.drag_marker_index, timestamp)
            self.creating_marker = False
            self.drag_marker_index = None
            self.drag_time = None
            self.update()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def leaveEvent(self, event) -> None:
        self.hover_x = None
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        painter.fillRect(self.rect(), QColor("#18201b"))
        content = self.rect().adjusted(0, 18, 0, -20)
        center_y = content.center().y()
        painter.setPen(QPen(QColor("#465149"), 1))
        painter.drawLine(content.left(), center_y, content.right(), center_y)
        if self.loading:
            painter.setPen(QColor("#dce6df"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Analyzing waveform...")
            return
        if self.error:
            painter.setPen(QColor("#ed9b91"))
            painter.drawText(self.rect().adjusted(12, 0, -12, 0), Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, self.error)
            return
        if not self.data:
            painter.setPen(QColor("#9ba79f"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "No waveform")
            return

        start, end = self.visible_window()
        span = max(end - start, 0.001)
        seconds_per_pixel = span / max(self.width(), 1)
        first_grid = math.ceil(max(start, 0) / 5) * 5
        painter.setPen(QPen(QColor("#2c3730"), 1))
        grid_time = first_grid
        while grid_time <= min(end, self.duration_seconds):
            x = (grid_time - start) / span * self.width()
            painter.drawLine(round(x), content.top(), round(x), content.bottom())
            painter.setPen(QColor("#829087"))
            painter.drawText(QRectF(x + 3, 1, 65, 16), f"{int(grid_time // 60)}:{grid_time % 60:04.1f}")
            painter.setPen(QPen(QColor("#2c3730"), 1))
            grid_time += 5

        playhead_x = (
            self.width() * self.position_seconds / max(self.duration_seconds, 0.001)
            if self.window_seconds is None
            else self.width() * self.playhead_fraction
        )
        for x in range(self.width()):
            sample_start_time = start + x * seconds_per_pixel
            sample_end_time = sample_start_time + seconds_per_pixel
            if sample_end_time < 0 or sample_start_time > self.duration_seconds:
                amplitude = 0.0
            else:
                first = max(0, int(sample_start_time * self.data.peaks_per_second))
                last = min(len(self.data.peaks), max(first + 1, math.ceil(sample_end_time * self.data.peaks_per_second)))
                amplitude = max(self.data.peaks[first:last], default=0.0)
            amplitude = amplitude ** 0.62
            half_height = max(1, amplitude * content.height() * 0.46)
            color = QColor("#668477") if x < playhead_x else QColor("#72c49c")
            painter.setPen(QPen(color, 1))
            painter.drawLine(x, round(center_y - half_height), x, round(center_y + half_height))

        painter.setPen(QPen(QColor("#e0a03f"), 1))
        painter.setBrush(QColor("#e0a03f"))
        for index, marker in enumerate(self.markers):
            if self.drag_marker_index == index and self.drag_time is not None:
                marker = self.drag_time
            if start <= marker <= end:
                x = (marker - start) / span * self.width()
                if index == self.selected_marker_index:
                    painter.setPen(QPen(QColor("#ffd36f"), 3))
                else:
                    painter.setPen(QPen(QColor("#e0a03f"), 1))
                painter.drawLine(round(x), content.top(), round(x), content.bottom())
                painter.drawPolygon(QPolygonF([
                    QPointF(x - 4, content.top()), QPointF(x + 4, content.top()), QPointF(x, content.top() + 6),
                ]))

        if self.creating_marker and self.drag_time is not None and start <= self.drag_time <= end:
            x = (self.drag_time - start) / span * self.width()
            painter.setPen(QPen(QColor("#ffd36f"), 2, Qt.PenStyle.DashLine))
            painter.drawLine(round(x), content.top(), round(x), content.bottom())

        delete_rect = self.delete_rect()
        if not delete_rect.isEmpty() and not self.creating_marker and self.drag_marker_index is None:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            painter.setPen(QPen(QColor("#ff6258"), 2))
            painter.setBrush(QColor("#3a1d1b"))
            painter.drawEllipse(delete_rect)
            inset = 5
            painter.drawLine(delete_rect.left() + inset, delete_rect.top() + inset, delete_rect.right() - inset, delete_rect.bottom() - inset)
            painter.drawLine(delete_rect.right() - inset, delete_rect.top() + inset, delete_rect.left() + inset, delete_rect.bottom() - inset)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)

        painter.setPen(QPen(QColor("#f04f43"), 2))
        painter.drawLine(round(playhead_x), content.top() - 5, round(playhead_x), content.bottom() + 5)
        painter.setPen(QColor("#f4f6f4"))
        label_x = playhead_x + 14
        if label_x + 84 > self.width():
            label_x = playhead_x - 98
        painter.drawText(QRectF(label_x, self.height() - 19, 84, 17), Qt.AlignmentFlag.AlignCenter, self._time_text(self.position_seconds))

        if self.hover_x is not None and self.marker_editable:
            hover_time = self.time_at_x(self.hover_x)
            painter.setPen(QPen(QColor("#ffffff"), 1, Qt.PenStyle.DotLine))
            painter.drawLine(round(self.hover_x), content.top(), round(self.hover_x), content.bottom())
            label_x = min(max(self.hover_x - 34, 2), self.width() - 70)
            painter.fillRect(QRectF(label_x, content.bottom() - 18, 68, 17), QColor("#253129"))
            painter.setPen(QColor("#ffffff"))
            painter.drawText(QRectF(label_x, content.bottom() - 18, 68, 17), Qt.AlignmentFlag.AlignCenter, self._time_text(hover_time))

    @staticmethod
    def _time_text(seconds: float) -> str:
        minutes = int(seconds // 60)
        return f"{minutes}:{seconds - minutes * 60:06.3f}"
