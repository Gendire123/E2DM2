from __future__ import annotations

import subprocess
from pathlib import Path

from PySide6.QtCore import QEvent, QSignalBlocker, QThreadPool, Qt, QUrl, Signal
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
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .catalog import duplicate_song, load_song_catalog, probe_audio_duration, save_custom_song, validate_song_manifest
from .entitlements import PRESET_EDITOR_FEATURE, EntitlementProvider
from .models import (
    DarkCue,
    EnergyLevel,
    FlashCue,
    HeartbeatSettings,
    SongManifest,
    SourceProgressionSettings,
    TransitionSettings,
)
from .waveform import WaveformData, WaveformTask, WaveformWidget


def _seconds_text(milliseconds: int) -> str:
    seconds = milliseconds / 1000
    minutes = int(seconds // 60)
    return f"{minutes}:{seconds - minutes * 60:06.3f}"


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
        self.table.itemChanged.connect(self._emit_values)
        self.table.currentCellChanged.connect(lambda row, _column, _old_row, _old_column: self.selection_changed.emit(row))
        add_button = QPushButton("Add")
        paste_button = QPushButton("Paste list")
        remove_button = QPushButton("Remove")
        sort_button = QPushButton("Sort")
        add_button.clicked.connect(lambda: self.add_value(0.0))
        paste_button.clicked.connect(self.paste_values)
        remove_button.clicked.connect(self.remove_selected)
        sort_button.clicked.connect(self.sort_values)
        buttons = QHBoxLayout()
        buttons.addWidget(add_button)
        buttons.addWidget(paste_button)
        buttons.addWidget(remove_button)
        buttons.addWidget(sort_button)
        buttons.addStretch()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.table)
        layout.addLayout(buttons)
        self.action_buttons = [add_button, paste_button, remove_button, sort_button]

    def _get_widget_row(self, widget: QWidget) -> int:
        for r in range(self.table.rowCount()):
            if self.table.cellWidget(r, 1) == widget:
                return r
        return -1

    def _on_plus_clicked(self, wrapper: QWidget) -> None:
        row = self._get_widget_row(wrapper)
        if row == -1:
            return
        combo_wrapper = self._create_effect_widget("heartbeat")
        self.table.setCellWidget(row, 1, combo_wrapper)
        combo = combo_wrapper.findChild(QComboBox)
        if combo:
            combo.showPopup()
        self._emit_effects()

    def _on_combo_changed(self, wrapper: QWidget, index: int) -> None:
        row = self._get_widget_row(wrapper)
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
                "border: 1px solid #a0a0a0; background-color: #ffffff; color: #333333; padding: 0px 0px 3px 0px; } "
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
        self.table.setItem(row, 0, QTableWidgetItem(f"{value:.6f}"))
        wrapper = self._create_effect_widget(effect)
        self.table.setCellWidget(row, 1, wrapper)
        self.table.scrollToBottom()
        self._emit_values()
        self._emit_effects()

    def values(self) -> list[float]:
        values = []
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item and item.text().strip():
                try:
                    values.append(float(item.text().strip()))
                except ValueError:
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
                self.table.setItem(row, 0, QTableWidgetItem(f"{value:.6f}"))
                wrapper = self._create_effect_widget(effect)
                self.table.setCellWidget(row, 1, wrapper)
        self.values_changed.emit(self.values())
        self.effects_changed.emit(self.effects())

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
            item = self.table.item(row, 0)
            if item:
                self.table.scrollToItem(item)

    def set_visible_row_count(self, rows: int) -> None:
        row_height = 31
        self.table.verticalHeader().setDefaultSectionSize(row_height)
        header_height = self.table.horizontalHeader().sizeHint().height()
        table_height = header_height + rows * row_height + self.table.frameWidth() * 2 + 2
        self.table.setFixedHeight(table_height)
        action_height = max(button.sizeHint().height() for button in self.action_buttons)
        self.setFixedHeight(table_height + self.layout().spacing() + action_height)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)


class SongEditorDialog(QDialog):
    catalog_changed = Signal()

    def __init__(self, entitlement: EntitlementProvider, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Epic Song Library")
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowMinMaxButtonsHint)
        self.resize(1220, 700)
        self.entitlement = entitlement
        self.songs: list[SongManifest] = []
        self.current: SongManifest | None = None
        self.audio_source: Path | None = None
        self.waveform_source = ""
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
        self.save_button = QPushButton("Save")
        self.new_button.clicked.connect(self.new_song)
        self.duplicate_button.clicked.connect(self.duplicate_current)
        self.save_button.clicked.connect(self.save_current)
        left_buttons = QHBoxLayout()
        left_buttons.addWidget(self.new_button)
        left_buttons.addWidget(self.duplicate_button)
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.addWidget(QLabel("Epic songs"))
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
        for label, control in [
            ("Title", self.title_edit), ("Artist", self.artist_edit), ("Song ID", self.id_edit),
            ("Moods (comma separated)", self.moods_edit), ("Energy", self.energy_combo), ("BPM", self.bpm_spin),
            ("Audio", audio_row), ("Montage duration", self.total_spin),
            ("Minimum source duration", self.minimum_source_spin), ("Opening fade", self.opening_spin),
            ("Fade starts", self.cuts_end_spin), ("Fade duration", self.fade_out_spin),
            ("Escalation cue", self.escalation_spin), ("Transition duration", self.transition_spin),
            ("Hard-cut threshold", self.hard_cut_spin), ("Short-cut threshold", self.short_threshold_spin),
            ("Short-cut source advance", self.short_advance_spin),
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
        self.waveform_zoom.addItem("20 sec", 20.0)
        self.waveform_zoom.addItem("40 sec", 40.0)
        self.waveform_zoom.addItem("60 sec", 60.0)
        self.waveform_zoom.addItem("Full song", None)
        self.waveform_zoom.setCurrentIndex(1)
        self.add_playhead_button = QPushButton("Add cut at playhead")
        self.add_playhead_button.clicked.connect(lambda: self.add_cut_timestamp(self.player.position() / 1000))
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
        self.waveform_zoom.currentIndexChanged.connect(
            lambda: self.waveform.set_window_seconds(self.waveform_zoom.currentData())
        )
        self.cut_markers = MarkerTable("Cut timestamp (seconds)")
        self.cut_markers.set_visible_row_count(7)
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
        self.position_label.setText(_seconds_text(position))
        self.waveform.set_position(position / 1000)
        if not self.position_slider.isSliderDown():
            self.position_slider.setValue(position)

    def reload_catalog(self, select_id: str | None = None) -> None:
        try:
            self.songs = load_song_catalog()
        except ValueError as exc:
            QMessageBox.critical(self, "Library error", str(exc))
            self.songs = []
        self.song_list.clear()
        selected_row = 0
        for row, song in enumerate(self.songs):
            suffix = "  [built-in]" if song.readonly else ""
            self.song_list.addItem(song.title + suffix)
            if song.song_id == select_id:
                selected_row = row
        if self.songs:
            self.song_list.setCurrentRow(selected_row)

    def _load_selected(self, row: int) -> None:
        if not 0 <= row < len(self.songs):
            return
        song = self.songs[row]
        self.current = song
        self.audio_source = song.audio_path
        self.title_edit.setText(song.title)
        self.artist_edit.setText(song.artist)
        self.id_edit.setText(song.song_id)
        self.moods_edit.setText(", ".join(song.moods))
        self.energy_combo.setCurrentText(song.energy.value.title())
        self.bpm_spin.setValue(song.bpm or 0)
        self.audio_edit.setText(str(song.audio_path))
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
        self.player.setSource(QUrl.fromLocalFile(str(song.audio_path)))
        self.load_waveform(song.audio_path)
        # For now, built-in songs CAN be edited (cuts, effects values, etc.)
        can_edit = self.entitlement.has_feature(PRESET_EDITOR_FEATURE)
        self._set_editable(can_edit)
        self.status_label.setText("Built-in preset (Editable for now)" if song.readonly else "Custom preset")

    def _set_editable(self, editable: bool) -> None:
        controls = [
            self.title_edit, self.artist_edit, self.moods_edit, self.energy_combo, self.bpm_spin, self.audio_edit,
            self.audio_button, self.total_spin, self.minimum_source_spin, self.opening_spin, self.cuts_end_spin,
            self.fade_out_spin, self.escalation_spin, self.transition_spin, self.hard_cut_spin,
            self.short_threshold_spin, self.short_advance_spin, self.cut_markers,
        ]
        for control in controls:
            control.setEnabled(editable)
        self.id_edit.setEnabled(editable and bool(self.current and self.current.manifest_path is None))
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
        path, _ = QFileDialog.getOpenFileName(self, "Add Epic song", "", "Audio (*.m4a *.mp3 *.wav *.aac *.flac)")
        if not path:
            return
        title = Path(path).stem
        song_id = "-".join(part for part in title.lower().replace("_", "-").split("-") if part.isalnum()) or "custom-song"
        self.current = SongManifest(
            schema_version=1, song_id=song_id, title=title, artist="", audio_file=Path(path).name,
            moods=["epic"], bpm=None, energy=EnergyLevel.HIGH, total_duration_seconds=1,
            minimum_source_duration_seconds=1, opening_fade_seconds=0, cuts_end_seconds=1,
            fade_out_seconds=0, escalation_seconds=0, cut_timestamps=[0], readonly=False,
        )
        self.audio_source = Path(path)
        self.songs.append(self.current)
        self.song_list.addItem(f"{title}  [unsaved]")
        self.song_list.setCurrentRow(self.song_list.count() - 1)
        self.audio_source = Path(path)
        self.audio_edit.setText(path)
        self.player.setSource(QUrl.fromLocalFile(path))
        self.load_waveform(Path(path))
        try:
            audio_duration = probe_audio_duration(Path(path))
            self.total_spin.setValue(audio_duration)
            self.minimum_source_spin.setValue(audio_duration)
            self.cuts_end_spin.setValue(audio_duration)
        except ValueError:
            pass
        self._set_editable(True)
        self.status_label.setText("New custom preset")

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
            # For now, built-in songs CAN be edited (preserve manifest_path)
            manifest_path=self.current.manifest_path if self.current else None,
        )

    def save_current(self) -> None:
        if not self.audio_source:
            QMessageBox.warning(self, "Missing audio", "Choose an audio file first.")
            return
        try:
            song = self._collect_song()
        except ValueError as exc:
            QMessageBox.warning(self, "Invalid value", str(exc))
            return
        errors = validate_song_manifest(song, require_audio=False)
        if errors:
            QMessageBox.warning(self, "Preset validation", "\n".join(errors))
            return
        try:
            save_custom_song(song, self.audio_source)
            self.catalog_changed.emit()
            self.reload_catalog(song.song_id)
            self.status_label.setText("Preset saved")
        except (OSError, ValueError) as exc:
            QMessageBox.critical(self, "Could not save preset", str(exc))

    def done(self, result: int) -> None:
        self.player.stop()
        super().done(result)
