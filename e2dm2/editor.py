from __future__ import annotations

import shutil
import subprocess
import re
import logging
from pathlib import Path

LOGGER = logging.getLogger(__name__)

from PySide6.QtCore import QEvent, QSignalBlocker, QThreadPool, QTimer, Qt, QUrl, Signal
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSlider,
    QSizePolicy,
    QSplitter,
    QStyle,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .catalog import (
    BUILTIN_SONG_ROOT,
    FULL_LENGTH_TRACKS,
    duplicate_song,
    load_song_catalog,
    probe_audio_duration,
    save_custom_song,
    validate_song_manifest,
)
from .entitlements import PRESET_EDITOR_FEATURE, EntitlementProvider
from .models import (
    DarkCue,
    EnergyLevel,
    FlashCue,
    HeartbeatSettings,
    SongManifest,
    SourceProgressionSettings,
    TransitionSettings,
    WorkflowMode,
)
from .waveform import WaveformData, WaveformTask, WaveformWidget


def _seconds_text(milliseconds: int) -> str:
    seconds = milliseconds / 1000
    minutes = int(seconds // 60)
    return f"{minutes}:{seconds - minutes * 60:06.3f}"


PLAYBACK_LATENCY_MS = 300


def _spin(maximum: float = 100000.0, decimals: int = 3) -> QDoubleSpinBox:
    control = QDoubleSpinBox()
    control.setRange(0, maximum)
    control.setDecimals(decimals)
    control.setSingleStep(0.1)
    return control


EFFECT_OPTIONS = [
    ("None", "none"),
    ("Heartbeat Flash", "heartbeat"),
    ("Sepia Color", "sepia"),
    ("Slow Fade Out", "slow_fade_out"),
    ("Flash Effect", "flash"),
]


class ClickPassingWidget(QWidget):
    def __init__(self, table: QTableWidget, label: QLabel, x_btn: QLabel, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.table = table
        self.label = label
        self.x_btn = x_btn
        
        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 2, 6, 2)
        layout.setSpacing(4)
        layout.addWidget(label, 1)
        layout.addWidget(x_btn)
        
        self.setStyleSheet("background: transparent;")
        
    def mousePressEvent(self, event) -> None:
        row = -1
        for r in range(self.table.rowCount()):
            if self.table.cellWidget(r, 0) == self:
                row = r
                break
        if row != -1:
            self.table.setCurrentCell(row, 0)
            self.table.selectRow(row)
        super().mousePressEvent(event)


class MarkerTable(QWidget):
    values_changed = Signal(object)
    effects_changed = Signal(object)
    selection_changed = Signal(int)

    def __init__(self, label: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels([label, "Visual Effect"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(0, 220)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.currentCellChanged.connect(lambda row, _column, _old_row, _old_column: self.selection_changed.emit(row))
        self.table.itemSelectionChanged.connect(self._update_x_visibility)
        self.table.currentCellChanged.connect(lambda: self._update_x_visibility())
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.table)

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.EnabledChange:
            self._update_x_visibility()
        super().changeEvent(event)

    def _get_widget_row(self, widget: QWidget, col: int) -> int:
        for r in range(self.table.rowCount()):
            if self.table.cellWidget(r, col) == widget:
                return r
        return -1

    def _on_plus_clicked(self, wrapper: QWidget) -> None:
        row = self._get_widget_row(wrapper, 1)
        if row == -1:
            return
        combo_wrapper = self._create_effect_widget("heartbeat")
        self.table.setCellWidget(row, 1, combo_wrapper)
        combo = combo_wrapper.findChild(QComboBox)
        if combo:
            combo.showPopup()
        self._emit_effects()

    def _on_combo_changed(self, wrapper: QWidget, index: int) -> None:
        row = self._get_widget_row(wrapper, 1)
        if row == -1:
            return
        combo = wrapper.findChild(QComboBox)
        if not combo:
            return
        val = combo.currentData()
        if val == "none":
            btn_wrapper = self._create_effect_widget("none")
            self.table.setCellWidget(row, 1, btn_wrapper)
        self._emit_effects()

    def _on_x_clicked(self, wrapper: QWidget) -> None:
        row = self._get_widget_row(wrapper, 0)
        if row == -1:
            return
        self.table.removeRow(row)
        self._emit_values()
        self._emit_effects()

    def _update_x_visibility(self) -> None:
        selected_rows = {index.row() for index in self.table.selectedIndexes()}
        is_editable = self.isEnabled()
        for row in range(self.table.rowCount()):
            wrapper = self.table.cellWidget(row, 0)
            if wrapper:
                x_btn = wrapper.findChild(QLabel, "x_btn")
                label = wrapper.findChild(QLabel, "ts_label")
                is_selected = row in selected_rows
                if x_btn:
                    x_btn.setVisible(is_selected and is_editable)
                if label:
                    if is_selected:
                        label.setStyleSheet("background: transparent; color: #ffffff; font-size: 13px;")
                    else:
                        label.setStyleSheet("background: transparent; color: #333333; font-size: 13px;")

    def _create_timestamp_widget(self, value: float) -> QWidget:
        label = QLabel(f"{value:.6f}")
        label.setObjectName("ts_label")
        label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        label.setStyleSheet("background: transparent; color: #333333; font-size: 13px;")
        
        x_btn = QLabel("×")
        x_btn.setObjectName("x_btn")
        x_btn.setFixedSize(16, 16)
        x_btn.setAlignment(Qt.AlignmentFlag.AlignCenter)
        x_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        x_btn.setStyleSheet(
            "QLabel { font-weight: bold; font-size: 14px; color: #ffffff; background-color: rgba(255, 255, 255, 0.2); border-radius: 8px; padding-bottom: 2px; }"
            "QLabel:hover { background-color: rgba(255, 255, 255, 0.4); }"
        )
        # Create wrapper
        wrapper = ClickPassingWidget(self.table, label, x_btn)
        x_btn.mousePressEvent = lambda event: self._on_x_clicked(wrapper)
        x_btn.setVisible(False)
        
        return wrapper

    def _create_effect_widget(self, effect_val: str) -> QWidget:
        wrapper = QWidget()
        layout = QHBoxLayout(wrapper)
        layout.setContentsMargins(6, 2, 6, 2)
        if effect_val == "none" or not effect_val:
            layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
            btn = QLabel("+")
            btn.setFixedSize(24, 24)
            btn.setAlignment(Qt.AlignmentFlag.AlignCenter)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(
                "QLabel { font-weight: bold; font-size: 16px; border-radius: 12px; "
                "border: 1px solid #a0a0a0; background-color: #fcfcfc; color: #333333; padding: 0px 0px 3px 0px; } "
                "QLabel:hover { background-color: #f5f5f5; border-color: #666666; }"
            )
            btn.mousePressEvent = lambda event: self._on_plus_clicked(wrapper)
            layout.addWidget(btn)
        else:
            layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)
            combo = QComboBox()
            for name, val in EFFECT_OPTIONS:
                combo.addItem(name, val)
            idx = combo.findData(effect_val)
            combo.setCurrentIndex(max(0, idx))
            combo.currentIndexChanged.connect(lambda index: self._on_combo_changed(wrapper, index))
            layout.addWidget(combo)
        return wrapper

    def add_value(self, value: float, effect: str = "none") -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        ts_wrapper = self._create_timestamp_widget(value)
        self.table.setCellWidget(row, 0, ts_wrapper)
        wrapper = self._create_effect_widget(effect)
        self.table.setCellWidget(row, 1, wrapper)
        self.table.scrollToBottom()
        self._emit_values()
        self._emit_effects()
        self._update_x_visibility()

    def values(self) -> list[float]:
        values = []
        for row in range(self.table.rowCount()):
            wrapper = self.table.cellWidget(row, 0)
            if wrapper:
                label = wrapper.findChild(QLabel, "ts_label")
                if label and label.text().strip():
                    try:
                        values.append(float(label.text().strip()))
                    except ValueError:
                        values.append(0.0)
                else:
                    values.append(0.0)
            else:
                values.append(0.0)
        return values

    def effects(self) -> list[str]:
        effects = []
        for row in range(self.table.rowCount()):
            wrapper = self.table.cellWidget(row, 1)
            if wrapper:
                combo = wrapper.findChild(QComboBox)
                if combo:
                    effects.append(combo.currentData())
                else:
                    effects.append("none")
            else:
                effects.append("none")
        return effects

    def set_values_and_effects(self, values: list[float], effects: list[str]) -> None:
        if len(effects) < len(values):
            effects = effects + ["none"] * (len(values) - len(effects))
        elif len(effects) > len(values):
            effects = effects[:len(values)]
        with QSignalBlocker(self.table):
            self.table.setRowCount(0)
            for value, effect in zip(values, effects):
                row = self.table.rowCount()
                self.table.insertRow(row)
                ts_wrapper = self._create_timestamp_widget(value)
                self.table.setCellWidget(row, 0, ts_wrapper)
                wrapper = self._create_effect_widget(effect)
                self.table.setCellWidget(row, 1, wrapper)
        self.values_changed.emit(self.values())
        self.effects_changed.emit(self.effects())
        self._update_x_visibility()

    def set_values(self, values: list[float]) -> None:
        self.set_values_and_effects(values, ["none"] * len(values))

    def sort_values(self) -> None:
        pairs = list(zip(self.values(), self.effects()))
        pairs.sort(key=lambda p: p[0])
        sorted_vals = [p[0] for p in pairs]
        sorted_effects = [p[1] for p in pairs]
        self.set_values_and_effects(sorted_vals, sorted_effects)

    def remove_selected(self) -> None:
        for row in sorted({index.row() for index in self.table.selectedIndexes()}, reverse=True):
            self.table.removeRow(row)
        self._emit_values()
        self._emit_effects()

    def paste_values(self) -> None:
        text, accepted = QInputDialog.getMultiLineText(self, "Paste timestamps", "One timestamp per line")
        if not accepted:
            return
        try:
            values = [float(value.strip()) for value in text.replace(",", "\n").splitlines() if value.strip()]
        except ValueError:
            QMessageBox.warning(self, "Invalid timestamps", "Every timestamp must be a number of seconds.")
            return
        self.set_values_and_effects(sorted(set(values)), ["none"] * len(values))

    def _emit_values(self) -> None:
        try:
            self.values_changed.emit(self.values())
        except ValueError:
            return

    def _emit_effects(self) -> None:
        self.effects_changed.emit(self.effects())

    def select_row(self, row: int) -> None:
        if 0 <= row < self.table.rowCount():
            self.table.setCurrentCell(row, 0)
            self.table.selectRow(row)
            self.table.scrollTo(self.table.model().index(row, 0))

    def set_visible_row_count(self, rows: int) -> None:
        row_height = 31
        self.table.verticalHeader().setDefaultSectionSize(row_height)
        header_height = self.table.horizontalHeader().sizeHint().height()
        table_height = header_height + rows * row_height + self.table.frameWidth() * 2 + 2
        self.table.setFixedHeight(table_height)
        self.setFixedHeight(table_height)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)


class WorkflowSelectionDialog(QDialog):
    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        audio_path: Path | None = None,
        suggestions: dict[str, tuple[str, str]] | None = None,
        initial_workflow: WorkflowMode | None = None,
        lock_workflow: bool = False,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("New Song Details")
        self.setModal(True)
        self.setMinimumWidth(460)
        self.suggestions = suggestions or {}

        title = QLabel("Add song to library")
        title.setStyleSheet("font-size: 15pt; font-weight: 650; color: #142033;")
        description = QLabel("Confirm how this audio file should appear in the music library.")
        description.setWordWrap(True)
        description.setStyleSheet("color: #66758A;")

        form = QFormLayout()
        self.audio_edit = QLineEdit()
        self.audio_edit.setReadOnly(True)
        self.audio_edit.setPlaceholderText("Choose an audio file")
        self.audio_button = QToolButton()
        self.audio_button.setText("Browse...")
        self.audio_button.clicked.connect(self.choose_audio)
        audio_row = QWidget()
        audio_layout = QHBoxLayout(audio_row)
        audio_layout.setContentsMargins(0, 0, 0, 0)
        audio_layout.addWidget(self.audio_edit, 1)
        audio_layout.addWidget(self.audio_button)
        form.addRow("Audio file", audio_row)

        self.combo = QComboBox()
        self.combo.addItem("Epic Montage", "epic_montage")
        self.combo.addItem("Full-length Video", "full_length")
        self.combo.addItem("Real Estate Showcase", "real_estate")
        if initial_workflow is not None:
            val = initial_workflow.value if hasattr(initial_workflow, "value") else initial_workflow
            self.combo.setCurrentIndex(max(0, self.combo.findData(val)))
        self.combo.setEnabled(not lock_workflow)
        self.title_edit = QLineEdit()
        self.title_edit.setPlaceholderText("Song title")
        self.id_edit = QLineEdit()
        self.id_edit.setPlaceholderText("lowercase-song-id")
        form.addRow("Workflow", self.combo)
        form.addRow("Title", self.title_edit)
        form.addRow("Song ID", self.id_edit)

        self.builtin_cb = QCheckBox("Add to the built-in library")
        self.builtin_cb.setToolTip("Built-in songs are stored with the application. Leave unchecked for your personal library.")
        self.combo.currentIndexChanged.connect(self._apply_suggestion)
        self._apply_suggestion()
        if audio_path is not None:
            self.set_audio_path(audio_path)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 18)
        layout.setSpacing(14)
        layout.addWidget(title)
        layout.addWidget(description)
        layout.addLayout(form)
        layout.addWidget(self.builtin_cb)
        layout.addWidget(buttons)

    def _apply_suggestion(self) -> None:
        title, song_id = self.suggestions.get(self.selected_workflow(), ("", ""))
        self.title_edit.setText(title)
        self.id_edit.setText(song_id)

    def choose_audio(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Add song", "", "Audio (*.m4a *.mp3 *.wav *.aac *.flac)",
        )
        if path:
            self.set_audio_path(Path(path))
        self.raise_()
        self.activateWindow()

    def set_audio_path(self, path: Path) -> None:
        self.audio_edit.setText(str(path))
        self.audio_edit.setToolTip(str(path))
        title = path.stem
        song_id = "-".join(
            part for part in re.split(r"[^a-z0-9]+", title.lower()) if part
        ) or "custom-song"
        for key in ["epic_montage", "full_length", "real_estate"]:
            self.suggestions[key] = (title, song_id)
        self.title_edit.setText(title)
        self.id_edit.setText(song_id)

    def selected_audio_path(self) -> Path | None:
        value = self.audio_edit.text().strip()
        return Path(value) if value else None

    def exec(self) -> int:
        if self.selected_audio_path() is None:
            path, _ = QFileDialog.getOpenFileName(
                self.parentWidget(), "Add song", "", "Audio (*.m4a *.mp3 *.wav *.aac *.flac)",
            )
            if not path:
                return QDialog.DialogCode.Rejected
            self.set_audio_path(Path(path))
        return super().exec()

    def selected_workflow(self) -> str:
        return self.combo.currentData()

    def is_builtin(self) -> bool:
        return self.builtin_cb.isChecked()

    def song_title(self) -> str:
        return self.title_edit.text().strip()

    def song_id(self) -> str:
        return self.id_edit.text().strip()

    def accept(self) -> None:
        if self.selected_audio_path() is None:
            QMessageBox.warning(self, "Audio file", "Choose an audio file for the song.")
            return
        if not self.song_title():
            QMessageBox.warning(self, "Song title", "Enter a title for the song.")
            return
        if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", self.song_id()):
            QMessageBox.warning(self, "Song ID", "Use lowercase letters, numbers, and single hyphens only.")
            return
        super().accept()


class SongEditorDialog(QDialog):
    catalog_changed = Signal()

    def __init__(self, entitlement: EntitlementProvider, parent: QWidget | None = None, workflow_filter: WorkflowMode | None = None) -> None:
        super().__init__(parent)
        self.workflow_filter = workflow_filter
        
        if self.workflow_filter == WorkflowMode.REAL_ESTATE:
            title_text = "Real Estate Song Library"
        elif self.workflow_filter == WorkflowMode.EPIC_MONTAGE:
            title_text = "Epic Song Library"
        elif self.workflow_filter == WorkflowMode.FULL_LENGTH:
            title_text = "Full-length Song Library"
        elif self.workflow_filter == WorkflowMode.CUSTOM:
            title_text = "Custom Song Library"
        else:
            title_text = "Song Library"
            
        self.setWindowTitle(title_text)
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowMinMaxButtonsHint)
        self.resize(1220, 700)
        self.entitlement = entitlement
        self.songs: list[SongManifest] = []
        self.legacy_full_length_ids: set[str] = set()
        self.current: SongManifest | None = None
        self.audio_source: Path | None = None
        self.waveform_source = ""
        self.snapshot = None
        self.waveform_tasks: dict[str, WaveformTask] = {}
        self.waveform_pool = QThreadPool.globalInstance()
        self.selecting_from_waveform = False
        self.player = QMediaPlayer(self)
        self.audio_output = QAudioOutput(self)
        self.player.setAudioOutput(self.audio_output)
        self.audio_output.setVolume(0.7)
        self._build_ui()
        self._connect_player()
        self.cuts_tab.installEventFilter(self)
        for child in self.cuts_tab.findChildren(QWidget):
            child.installEventFilter(self)
        self.reload_catalog()
        allowed = self.entitlement.has_feature(PRESET_EDITOR_FEATURE)
        self.new_button.setEnabled(allowed)
        self.duplicate_button.setEnabled(allowed)
        if not allowed:
            self.status_label.setText("Preset editing requires the Pro editor entitlement.")

    def _build_ui(self) -> None:
        self.song_list = QListWidget()
        self.song_list.setMinimumWidth(235)
        self.song_list.currentRowChanged.connect(self._load_selected)
        self.new_button = QPushButton("New song")
        self.duplicate_button = QPushButton("Duplicate")
        self.delete_button = QPushButton("Delete")
        self.save_button = QPushButton("Save")
        self.new_button.clicked.connect(self.new_song)
        self.duplicate_button.clicked.connect(self.duplicate_current)
        self.delete_button.clicked.connect(self.delete_current)
        self.save_button.clicked.connect(self.save_current)
        left_buttons = QHBoxLayout()
        left_buttons.addWidget(self.new_button)
        left_buttons.addWidget(self.duplicate_button)
        left_buttons.addWidget(self.delete_button)
        left = QWidget()
        left_layout = QVBoxLayout(left)
        
        if self.workflow_filter == WorkflowMode.REAL_ESTATE:
            label_text = "Real Estate songs"
        elif self.workflow_filter == WorkflowMode.EPIC_MONTAGE:
            label_text = "Epic songs"
        elif self.workflow_filter == WorkflowMode.FULL_LENGTH:
            label_text = "Full-length songs"
        elif self.workflow_filter == WorkflowMode.CUSTOM:
            label_text = "Custom songs"
        else:
            label_text = "Songs"
            
        left_layout.addWidget(QLabel(label_text))
        left_layout.addWidget(self.song_list)
        left_layout.addLayout(left_buttons)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._general_tab(), "General")
        self.cuts_tab = self._timing_tab()
        self.tabs.addTab(self.cuts_tab, "Cuts")
        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        self.status_label.setObjectName("statusLabel")
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.addWidget(self.tabs)
        footer = QHBoxLayout()
        footer.addWidget(self.status_label, 1)
        footer.addWidget(self.save_button)
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.accept)
        footer.addWidget(close_button)
        right_layout.addLayout(footer)

        splitter = QSplitter()
        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setStretchFactor(1, 1)
        layout = QVBoxLayout(self)
        layout.addWidget(splitter)

    def _general_tab(self) -> QWidget:
        content = QWidget()
        form = QFormLayout(content)
        self.title_edit = QLineEdit()
        self.artist_edit = QLineEdit()
        self.id_edit = QLineEdit()
        self.moods_edit = QLineEdit()
        self.energy_combo = QComboBox()
        self.energy_combo.addItems([value.value.title() for value in EnergyLevel])
        self.bpm_spin = _spin(400, 2)
        self.bpm_spin.setSpecialValueText("Unknown")
        self.audio_edit = QLineEdit()
        self.audio_button = QToolButton()
        self.audio_button.setText("...")
        self.audio_button.setToolTip("Choose audio file")
        self.audio_button.clicked.connect(self.choose_audio)
        audio_row = QWidget()
        audio_layout = QHBoxLayout(audio_row)
        audio_layout.setContentsMargins(0, 0, 0, 0)
        audio_layout.addWidget(self.audio_edit)
        audio_layout.addWidget(self.audio_button)
        self.total_spin = _spin()
        self.minimum_source_spin = _spin()
        self.opening_spin = _spin()
        self.cuts_end_spin = _spin()
        self.fade_out_spin = _spin()
        self.escalation_spin = _spin()
        self.transition_spin = _spin(30)
        self.hard_cut_spin = _spin(30)
        self.short_threshold_spin = _spin(60)
        self.short_advance_spin = _spin(60)
        # Retain these controls as internal value holders for manifest
        # compatibility, but do not expose rendering metadata to users.
        for control in (
            self.bpm_spin,
            self.total_spin,
            self.minimum_source_spin,
            self.opening_spin,
            self.cuts_end_spin,
            self.fade_out_spin,
            self.escalation_spin,
            self.hard_cut_spin,
            self.short_threshold_spin,
            self.short_advance_spin,
        ):
            control.setParent(content)
            control.hide()
        for label, control in [
            ("Title", self.title_edit), ("Artist", self.artist_edit), ("Song ID", self.id_edit),
            ("Moods (comma separated)", self.moods_edit), ("Energy", self.energy_combo),
            ("Audio", audio_row), ("Transition duration", self.transition_spin),
        ]:
            form.addRow(label, control)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(content)
        return scroll

    def _timing_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        controls = QHBoxLayout()
        self.play_button = QToolButton()
        self.play_button.setText("Play")
        self.play_button.setToolTip("Play or pause audio")
        self.play_button.clicked.connect(self.toggle_playback)
        self.position_label = QLabel("0:00.000")
        self.position_slider = QSlider(Qt.Orientation.Horizontal)
        self.position_slider.setRange(0, 0)
        self.position_slider.sliderMoved.connect(self.player.setPosition)
        self.waveform_zoom = QComboBox()
        self.waveform_zoom.setToolTip("Visible waveform duration")
        self.waveform_zoom.addItem("10 sec", 10.0)
        self.waveform_zoom.addItem("20 sec", 20.0)
        self.waveform_zoom.addItem("40 sec", 40.0)
        self.waveform_zoom.addItem("60 sec", 60.0)
        self.waveform_zoom.addItem("Full song", None)
        self.waveform_zoom.setCurrentIndex(2)
        self.add_playhead_button = QPushButton("Add cut at playhead")
        self.add_playhead_button.clicked.connect(lambda: self.add_cut_timestamp(self._current_playback_time()))
        controls.addWidget(self.play_button)
        controls.addWidget(self.position_label)
        controls.addWidget(self.position_slider, 1)
        controls.addWidget(self.waveform_zoom)
        controls.addWidget(self.add_playhead_button)
        self.waveform = WaveformWidget()
        self.waveform.timestamp_added.connect(self.add_cut_timestamp)
        self.waveform.marker_selected.connect(self.select_cut_from_waveform)
        self.waveform.marker_moved.connect(self.move_cut_timestamp)
        self.waveform.marker_remove_requested.connect(self.remove_cut_timestamp)
        self.waveform.position_requested.connect(
            lambda secs: self.player.setPosition(round(secs * 1000))
        )
        self.waveform_zoom.currentIndexChanged.connect(
            lambda: self.waveform.set_window_seconds(self.waveform_zoom.currentData())
        )
        self.cut_markers = MarkerTable("Cut timestamp (seconds)")
        self.cut_markers.set_visible_row_count(10)
        self.cut_markers.values_changed.connect(self.waveform.set_markers)
        self.cut_markers.selection_changed.connect(self.select_cut_from_table)
        layout.addLayout(controls)
        layout.addWidget(self.waveform)
        layout.addWidget(self.cut_markers)
        return widget

    def _connect_player(self) -> None:
        self.player.positionChanged.connect(self._position_changed)
        self.player.durationChanged.connect(self.position_slider.setMaximum)
        self.player.durationChanged.connect(self.waveform.set_duration)
        self.player.playbackStateChanged.connect(
            lambda state: self.play_button.setText("Pause" if state == QMediaPlayer.PlaybackState.PlayingState else "Play")
        )

    def _position_changed(self, position: int) -> None:
        corrected_position = position
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            corrected_position = max(0, position - PLAYBACK_LATENCY_MS)
        self.position_label.setText(_seconds_text(corrected_position))
        self.waveform.set_position(corrected_position / 1000)
        if not self.position_slider.isSliderDown():
            self.position_slider.setValue(corrected_position)

    def _current_playback_time(self) -> float:
        position = self.player.position()
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            position = max(0, position - PLAYBACK_LATENCY_MS)
        return position / 1000

    @property
    def filtered_songs(self) -> list[SongManifest]:
        if getattr(self, "workflow_filter", None) is not None:
            if self.workflow_filter == WorkflowMode.CUSTOM:
                return [s for s in self.songs if not s.readonly]
            return [s for s in self.songs if s.workflow == self.workflow_filter]
        return self.songs

    def _is_builtin_full_length(self, song: SongManifest) -> bool:
        manifest_folder = song.manifest_path.parent.name if song.manifest_path else ""
        return song.workflow == WorkflowMode.FULL_LENGTH and (
            song.song_id in self.legacy_full_length_ids or manifest_folder in self.legacy_full_length_ids
        )

    def reload_catalog(self, select_id: str | None = None) -> None:
        try:
            self.songs = load_song_catalog()
        except ValueError as exc:
            self._show_critical("Library error", str(exc))
            self.songs = []

        self.legacy_full_length_ids = {track.track_id for track in FULL_LENGTH_TRACKS}
        if self.workflow_filter == WorkflowMode.FULL_LENGTH:
            catalog_ids = {song.song_id for song in self.songs}
            for track in FULL_LENGTH_TRACKS:
                if track.track_id in catalog_ids or (track.path.parent / "preset.json").is_file():
                    continue
                self.songs.append(SongManifest(
                    schema_version=1,
                    song_id=track.track_id,
                    title=track.title,
                    artist="E2DM2 built-in library",
                    audio_file=str(track.path),
                    moods=[track.description],
                    bpm=None,
                    energy=EnergyLevel.MEDIUM,
                    total_duration_seconds=track.duration_seconds,
                    minimum_source_duration_seconds=track.duration_seconds,
                    opening_fade_seconds=0,
                    cuts_end_seconds=track.duration_seconds,
                    fade_out_seconds=0,
                    escalation_seconds=0,
                    cut_timestamps=[0],
                    effects=["none"],
                    workflow=WorkflowMode.FULL_LENGTH,
                    readonly=True,
                ))
            
        self.song_list.clear()
        selected_row = 0
        for row, song in enumerate(self.filtered_songs):
            suffix = "  [built-in]" if song.readonly else ""
            self.song_list.addItem(song.title + suffix)
            if song.song_id == select_id:
                selected_row = row
        if self.filtered_songs:
            self.song_list.setCurrentRow(selected_row)

    def _load_selected(self, row: int) -> None:
        songs = self.filtered_songs
        if not 0 <= row < len(songs):
            return
        song = songs[row]
        self.current = song
        is_legacy_full_length = self._is_builtin_full_length(song)
        if is_legacy_full_length:
            self.audio_source = song.audio_path
        elif not (song.manifest_path is None and hasattr(self, "audio_source") and self.audio_source and self.audio_source.is_absolute()):
            self.audio_source = song.audio_path
        self.title_edit.setText(song.title)
        self.artist_edit.setText(song.artist)
        self.id_edit.setText(song.song_id)
        self.moods_edit.setText(", ".join(song.moods))
        self.energy_combo.setCurrentText(song.energy.value.title())
        self.bpm_spin.setValue(song.bpm or 0)
        
        if is_legacy_full_length:
            display_path = song.audio_path
        elif song.manifest_path is None:
            # Predict the target path to show in the UI
            from .catalog import BUILTIN_SONG_ROOT, custom_library_root
            root = BUILTIN_SONG_ROOT if song.readonly else custom_library_root()
            display_path = root / song.song_id / song.audio_file
        else:
            display_path = self.audio_source
            
        self.audio_edit.setText(str(display_path))
        self.total_spin.setValue(song.total_duration_seconds)
        self.minimum_source_spin.setValue(song.minimum_source_duration_seconds)
        self.opening_spin.setValue(song.opening_fade_seconds)
        self.cuts_end_spin.setValue(song.cuts_end_seconds)
        self.fade_out_spin.setValue(song.fade_out_seconds)
        self.escalation_spin.setValue(song.escalation_seconds)
        self.transition_spin.setValue(song.transitions.duration_seconds)
        self.hard_cut_spin.setValue(song.transitions.hard_cut_threshold_seconds)
        self.short_threshold_spin.setValue(song.source_progression.short_cut_threshold_seconds)
        self.short_advance_spin.setValue(song.source_progression.short_cut_advance_seconds)
        self.cut_markers.set_values_and_effects(song.cut_timestamps, song.effects)
        self.player.setSource(QUrl.fromLocalFile(str(self.audio_source)))
        if is_legacy_full_length:
            self.waveform_source = ""
            self.waveform.set_error("Cut markers are not used by built-in full-length tracks.")
        else:
            self.load_waveform(self.audio_source)
        # For now, built-in songs CAN be edited (cuts, effects values, etc.)
        allowed = self.entitlement.has_feature(PRESET_EDITOR_FEATURE)
        self._set_editable(allowed)
        self.duplicate_button.setEnabled(allowed and not is_legacy_full_length)
        self.delete_button.setEnabled(allowed and not is_legacy_full_length)
        if is_legacy_full_length:
            self.status_label.setText("Built-in full-length track (Editable for now)")
        else:
            self.status_label.setText("Built-in preset (Editable for now)" if song.readonly else "Custom preset")
        self.snapshot = self._capture_snapshot()

    def _set_editable(self, editable: bool) -> None:
        controls = [
            self.title_edit, self.artist_edit, self.moods_edit, self.energy_combo, self.bpm_spin, self.audio_edit,
            self.audio_button, self.total_spin, self.minimum_source_spin, self.opening_spin, self.cuts_end_spin,
            self.fade_out_spin, self.escalation_spin, self.transition_spin, self.hard_cut_spin,
            self.short_threshold_spin, self.short_advance_spin, self.cut_markers,
        ]
        for control in controls:
            control.setEnabled(editable)
        self.id_edit.setEnabled(editable)
        self.play_button.setEnabled(True)
        self.position_slider.setEnabled(True)
        self.waveform_zoom.setEnabled(True)
        self.waveform.set_marker_editable(editable)
        self.add_playhead_button.setEnabled(editable)
        self.save_button.setEnabled(editable)

    def choose_audio(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Choose song", "", "Audio (*.m4a *.mp3 *.wav *.aac *.flac)")
        if path:
            self.audio_source = Path(path)
            self.audio_edit.setText(path)
            self.player.setSource(QUrl.fromLocalFile(path))
            self.load_waveform(Path(path))

    def toggle_playback(self) -> None:
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def eventFilter(self, watched, event) -> bool:
        if (
            self.tabs.currentWidget() is self.cuts_tab
            and event.type() == QEvent.Type.KeyPress
            and event.key() == Qt.Key.Key_Space
            and event.modifiers() == Qt.KeyboardModifier.NoModifier
        ):
            self.toggle_playback()
            event.accept()
            return True
        return super().eventFilter(watched, event)

    def new_song(self) -> None:
        try:
            epic_indices = [
                int(match.group(1)) for song in self.songs
                if (match := re.match(r"^epic-montage-(\d+)$", song.song_id))
            ]
            real_estate_indices = [
                int(match.group(1)) for song in self.songs
                if (match := re.match(r"^real-estate-(\d+)$", song.song_id))
            ]
            next_epic = max(epic_indices, default=0) + 1
            next_real_estate = max(real_estate_indices, default=0) + 1
            suggestions = {
                WorkflowMode.EPIC_MONTAGE.value: (f"Epic Montage {next_epic}", f"epic-montage-{next_epic}"),
                WorkflowMode.FULL_LENGTH.value: ("New Full-length Song", "new-full-length-song"),
                WorkflowMode.REAL_ESTATE.value: (f"Real Estate {next_real_estate}", f"real-estate-{next_real_estate}"),
            }
            wf_dialog = WorkflowSelectionDialog(
                self,
                suggestions=suggestions,
                initial_workflow=self.workflow_filter if (self.workflow_filter and self.workflow_filter != WorkflowMode.CUSTOM) else WorkflowMode.EPIC_MONTAGE,
                lock_workflow=self.workflow_filter is not None and self.workflow_filter != WorkflowMode.CUSTOM,
            )
            if wf_dialog.exec() != QDialog.DialogCode.Accepted:
                return

            path = wf_dialog.selected_audio_path()
            if path is None:
                return
            suffix_ext = path.suffix
            workflow_type = wf_dialog.selected_workflow()
            is_builtin = wf_dialog.is_builtin()
            title = wf_dialog.song_title()
            song_id = wf_dialog.song_id()

            if workflow_type == "epic_montage":
                audio_file_name = f"EpicMusic{next_epic}{suffix_ext}" if next_epic > 1 else f"EpicMusic{suffix_ext}"
            elif workflow_type == "real_estate":
                audio_file_name = f"RealEstate{next_real_estate}{suffix_ext}"
            else:
                audio_file_name = path.name

            self.current = SongManifest(
                schema_version=1, song_id=song_id, title=title, artist="User", audio_file=audio_file_name,
                moods=["epic"], bpm=None, energy=EnergyLevel.HIGH, total_duration_seconds=1,
                minimum_source_duration_seconds=1, opening_fade_seconds=0, cuts_end_seconds=1,
                fade_out_seconds=0, escalation_seconds=0, cut_timestamps=[0], effects=["none"],
                readonly=is_builtin, workflow=WorkflowMode(workflow_type)
            )
            self.audio_source = path
            self.songs.append(self.current)
            suffix = "  [built-in]" if is_builtin else "  [unsaved]"
            self.song_list.addItem(title + suffix)
            self.song_list.setCurrentRow(self.song_list.count() - 1)
            self.player.setSource(QUrl.fromLocalFile(str(path)))
            self.load_waveform(path)
            try:
                audio_duration = probe_audio_duration(path)
                self.total_spin.setValue(audio_duration)
                self.minimum_source_spin.setValue(audio_duration)
                self.cuts_end_spin.setValue(audio_duration)
            except ValueError:
                pass
            self._set_editable(True)
            self.status_label.setText("New built-in preset" if is_builtin else "New custom preset")
            self.save_current()
        except Exception as e:
            import traceback
            self._show_critical("Error in New Song", f"An error occurred: {str(e)}\n\n{traceback.format_exc()}")

    def add_cut_timestamp(self, timestamp: float) -> None:
        # For now, built-in songs CAN be edited
        if not self.current:
            return
        timestamp = max(0.0, min(float(timestamp), self.total_spin.value()))
        values = self.cut_markers.values()
        if any(abs(value - timestamp) < 0.0005 for value in values):
            return
        values.append(round(timestamp, 6))
        values = sorted(values)
        self.cut_markers.set_values(values)
        selected = min(range(len(values)), key=lambda index: abs(values[index] - timestamp))
        self.cut_markers.select_row(selected)

    def move_cut_timestamp(self, index: int, timestamp: float) -> None:
        values = self.cut_markers.values()
        if not 0 < index < len(values):
            return
        timestamp = max(0.0, min(float(timestamp), self.total_spin.value()))
        if any(other != index and abs(value - timestamp) < 0.0005 for other, value in enumerate(values)):
            self.waveform.set_markers(values)
            self.waveform.select_marker(index)
            return
        values[index] = round(timestamp, 6)
        values.sort()
        self.cut_markers.set_values(values)
        selected = min(range(len(values)), key=lambda row: abs(values[row] - timestamp))
        self.cut_markers.select_row(selected)

    def remove_cut_timestamp(self, index: int) -> None:
        values = self.cut_markers.values()
        if not 0 < index < len(values):
            return
        values.pop(index)
        self.cut_markers.set_values(values)
        if values:
            self.cut_markers.select_row(min(index, len(values) - 1))

    def select_cut_from_waveform(self, index: int) -> None:
        self.selecting_from_waveform = True
        try:
            self.cut_markers.select_row(index)
        finally:
            self.selecting_from_waveform = False

    def select_cut_from_table(self, index: int) -> None:
        values = self.cut_markers.values()
        self.waveform.select_marker(index)
        if not self.selecting_from_waveform and 0 <= index < len(values):
            self.player.setPosition(round(values[index] * 1000))

    def load_waveform(self, audio_path: Path) -> None:
        source = str(audio_path.resolve())
        self.waveform_source = source
        self.waveform.set_loading()
        task = WaveformTask(audio_path)
        self.waveform_tasks[source] = task
        task.signals.finished.connect(self._waveform_ready)
        task.signals.failed.connect(self._waveform_failed)
        self.waveform_pool.start(task)

    def _waveform_ready(self, source: str, data: WaveformData) -> None:
        self.waveform_tasks.pop(source, None)
        if source == self.waveform_source:
            self.waveform.set_waveform(data)
            self.waveform.set_markers(self.cut_markers.values())

    def _waveform_failed(self, source: str, message: str) -> None:
        self.waveform_tasks.pop(source, None)
        if source == self.waveform_source:
            self.waveform.set_error(message)

    def duplicate_current(self) -> None:
        if not self.current:
            return
        title, accepted = QInputDialog.getText(self, "Duplicate preset", "New title", text=f"{self.current.title} Copy")
        if not accepted or not title.strip():
            return
        default_id = "-".join(part for part in title.lower().replace("_", "-").split("-") if part.isalnum())
        song_id, accepted = QInputDialog.getText(self, "Duplicate preset", "New song ID", text=default_id)
        if not accepted or not song_id.strip():
            return
        try:
            duplicate_song(self.current, song_id.strip(), title.strip())
            self.catalog_changed.emit()
            self.reload_catalog(song_id.strip())
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Could not duplicate preset", str(exc))

    def delete_current(self) -> None:
        if not self.current:
            return
        song_title = self.current.title
        reply = QMessageBox.question(
            self,
            "Confirm Delete",
            f"Are you sure you want to delete the song '{song_title}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            manifest_path = self.current.manifest_path
            if manifest_path and manifest_path.exists():
                try:
                    manifest_path.unlink()
                    self.catalog_changed.emit()
                    self.reload_catalog()
                    self.status_label.setText(f"Deleted '{song_title}'")
                except Exception as exc:
                    QMessageBox.critical(self, "Could not delete preset", str(exc))

    def _collect_song(self) -> SongManifest:
        # Determine fallback cues/heartbeat for backward compatibility
        cut_vals = self.cut_markers.values()
        cut_effs = self.cut_markers.effects()
        
        hb_timestamps = [ts for ts, eff in zip(cut_vals, cut_effs) if eff == "heartbeat"]
        heartbeat = HeartbeatSettings(hb_timestamps, opacity=0.3, fade_seconds=0.5)
        
        flash = None
        for ts, eff in zip(cut_vals, cut_effs):
            if eff == "flash":
                flash = FlashCue(start_seconds=ts, duration_seconds=0.3, fade_in_seconds=0.05, opacity=0.8)
                break
                
        dark = None
        for ts, eff in zip(cut_vals, cut_effs):
            if eff == "slow_fade_out":
                dark = DarkCue(start_seconds=ts, end_seconds=ts + 1.5, fade_out_seconds=1.0, opacity=0.9)
                break

        return SongManifest(
            schema_version=1,
            song_id=self.id_edit.text().strip(),
            title=self.title_edit.text().strip(),
            artist=self.artist_edit.text().strip() or "Unknown",
            audio_file=Path(self.audio_edit.text()).name,
            moods=[value.strip() for value in self.moods_edit.text().split(",") if value.strip()],
            bpm=self.bpm_spin.value() or None,
            energy=EnergyLevel(self.energy_combo.currentText().lower()),
            total_duration_seconds=self.total_spin.value(),
            minimum_source_duration_seconds=self.minimum_source_spin.value(),
            opening_fade_seconds=self.opening_spin.value(),
            cuts_end_seconds=self.cuts_end_spin.value(),
            fade_out_seconds=self.fade_out_spin.value(),
            escalation_seconds=self.escalation_spin.value(),
            cut_timestamps=cut_vals,
            effects=cut_effs,
            transitions=TransitionSettings(self.transition_spin.value(), self.hard_cut_spin.value()),
            source_progression=SourceProgressionSettings(self.short_threshold_spin.value(), self.short_advance_spin.value()),
            heartbeat=heartbeat,
            dark_cue=dark,
            flash_cue=flash,
            workflow=self.current.workflow if self.current else WorkflowMode.EPIC_MONTAGE,
            readonly=self.current.readonly if self.current else False,
            manifest_path=self.current.manifest_path if self.current else None,
        )

    def _show_warning(self, title: str, text: str) -> None:
        import sys
        if "pytest" in sys.modules or "unittest" in sys.modules:
            LOGGER.warning("QMessageBox warning: %s - %s", title, text)
            return
        QMessageBox.warning(self, title, text)

    def _show_critical(self, title: str, text: str) -> None:
        import sys
        if "pytest" in sys.modules or "unittest" in sys.modules:
            LOGGER.error("QMessageBox critical: %s - %s", title, text)
            return
        QMessageBox.critical(self, title, text)

    def _show_saved_toast(self) -> None:
        import sys
        if "pytest" in sys.modules or "unittest" in sys.modules:
            return
        msg_box = QMessageBox(self)
        msg_box.setWindowTitle("Success")
        msg_box.setText("Song information has been successfully saved.")
        msg_box.setIcon(QMessageBox.Icon.Information)
        msg_box.setStandardButtons(QMessageBox.StandardButton.NoButton)
        QTimer.singleShot(2000, msg_box.accept)
        msg_box.exec()

    def _capture_snapshot(self) -> dict[str, Any]:
        return {
            "title": self.title_edit.text(),
            "artist": self.artist_edit.text(),
            "id": self.id_edit.text(),
            "moods": self.moods_edit.text(),
            "energy": self.energy_combo.currentText(),
            "bpm": self.bpm_spin.value(),
            "audio": self.audio_edit.text(),
            "total": self.total_spin.value(),
            "minimum": self.minimum_source_spin.value(),
            "opening": self.opening_spin.value(),
            "cuts_end": self.cuts_end_spin.value(),
            "fade_out": self.fade_out_spin.value(),
            "escalation": self.escalation_spin.value(),
            "transition": self.transition_spin.value(),
            "hard_cut": self.hard_cut_spin.value(),
            "short_threshold": self.short_threshold_spin.value(),
            "short_advance": self.short_advance_spin.value(),
            "cut_timestamps": list(self.cut_markers.values()),
            "cut_effects": list(self.cut_markers.effects()),
        }

    def save_current(self) -> bool:
        if not self.audio_source:
            self._show_warning("Missing audio", "Choose an audio file first.")
            return False
        try:
            song = self._collect_song()
        except ValueError as exc:
            self._show_warning("Invalid value", str(exc))
            return False
        errors = validate_song_manifest(song, require_audio=False)
        if errors:
            self._show_warning("Preset validation", "\n".join(errors))
            return False
        try:
            old_manifest_path = None
            if (
                self.current
                and self.current.manifest_path
                and self.current.song_id != song.song_id
                and not self._is_builtin_full_length(self.current)
            ):
                old_manifest_path = self.current.manifest_path
                song.manifest_path = None
            
            lib_root = BUILTIN_SONG_ROOT if (self.current and self.current.readonly) else None
            saved_song = save_custom_song(song, self.audio_source, library_root=lib_root)
            
            if old_manifest_path and old_manifest_path.exists():
                try:
                    old_manifest_path.unlink()
                except Exception:
                    pass
                try:
                    shutil.rmtree(old_manifest_path.parent)
                except Exception:
                    pass
            
            self.catalog_changed.emit()
            self.reload_catalog(saved_song.song_id)
            self.status_label.setText("Preset saved")
            self._show_saved_toast()
            return True
        except (OSError, ValueError) as exc:
            self._show_critical("Could not save preset", str(exc))
            return False

    def done(self, result: int) -> None:
        import sys
        is_testing = "pytest" in sys.modules or "unittest" in sys.modules
        if not is_testing and hasattr(self, "snapshot") and self.snapshot and self._capture_snapshot() != self.snapshot:
            reply = QMessageBox.question(
                self,
                "Unsaved Changes",
                "Do you really want to close without saving?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.No:
                if not self.save_current():
                    return
        
        self.player.stop()
        super().done(result)
