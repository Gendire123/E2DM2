from __future__ import annotations

import subprocess
from pathlib import Path

from PySide6.QtCore import QSignalBlocker, QThreadPool, Qt, QUrl, Signal
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
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QSlider,
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


class MarkerTable(QWidget):
    values_changed = Signal(object)

    def __init__(self, label: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.table = QTableWidget(0, 1)
        self.table.setHorizontalHeaderLabels([label])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.itemChanged.connect(self._emit_values)
        add_button = QPushButton("Add")
        paste_button = QPushButton("Paste list")
        remove_button = QPushButton("Remove")
        sort_button = QPushButton("Sort")
        add_button.clicked.connect(lambda: self.add_value(0.0))
        paste_button.clicked.connect(self.paste_values)
        remove_button.clicked.connect(self.remove_selected)
        sort_button.clicked.connect(lambda: self.set_values(sorted(set(self.values()))))
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

    def add_value(self, value: float) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setItem(row, 0, QTableWidgetItem(f"{value:.6f}"))
        self.table.scrollToBottom()

    def values(self) -> list[float]:
        values = []
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item and item.text().strip():
                values.append(float(item.text().strip()))
        return values

    def set_values(self, values: list[float]) -> None:
        with QSignalBlocker(self.table):
            self.table.setRowCount(0)
            for value in values:
                row = self.table.rowCount()
                self.table.insertRow(row)
                self.table.setItem(row, 0, QTableWidgetItem(f"{value:.6f}"))
        self.values_changed.emit(self.values())

    def remove_selected(self) -> None:
        for row in sorted({index.row() for index in self.table.selectedIndexes()}, reverse=True):
            self.table.removeRow(row)
        self._emit_values()

    def paste_values(self) -> None:
        text, accepted = QInputDialog.getMultiLineText(self, "Paste timestamps", "One timestamp per line")
        if not accepted:
            return
        try:
            values = [float(value.strip()) for value in text.replace(",", "\n").splitlines() if value.strip()]
        except ValueError:
            QMessageBox.warning(self, "Invalid timestamps", "Every timestamp must be a number of seconds.")
            return
        self.set_values(sorted(set(values)))

    def _emit_values(self) -> None:
        try:
            self.values_changed.emit(self.values())
        except ValueError:
            return


class SongEditorDialog(QDialog):
    catalog_changed = Signal()

    def __init__(self, entitlement: EntitlementProvider, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Epic Song Library")
        self.resize(1220, 820)
        self.entitlement = entitlement
        self.songs: list[SongManifest] = []
        self.current: SongManifest | None = None
        self.audio_source: Path | None = None
        self.waveform_source = ""
        self.waveform_tasks: dict[str, WaveformTask] = {}
        self.waveform_pool = QThreadPool.globalInstance()
        self.player = QMediaPlayer(self)
        self.audio_output = QAudioOutput(self)
        self.player.setAudioOutput(self.audio_output)
        self.audio_output.setVolume(0.7)
        self._build_ui()
        self._connect_player()
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
        self.tabs.addTab(self._timing_tab(), "Cuts")
        self.tabs.addTab(self._effects_tab(), "Effects")
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
        widget = QWidget()
        form = QFormLayout(widget)
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
        return widget

    def _timing_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
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
        self.waveform.timestamp_clicked.connect(self.add_cut_timestamp)
        self.waveform_zoom.currentIndexChanged.connect(
            lambda: self.waveform.set_window_seconds(self.waveform_zoom.currentData())
        )
        self.cut_markers = MarkerTable("Cut timestamp (seconds)")
        self.cut_markers.values_changed.connect(self.waveform.set_markers)
        layout.addLayout(controls)
        layout.addWidget(self.waveform)
        layout.addWidget(self.cut_markers)
        return widget

    def _effects_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        self.heartbeat_markers = MarkerTable("Heartbeat timestamp (seconds)")
        self.heartbeat_opacity = _spin(1, 3)
        self.heartbeat_fade = _spin(10)
        heartbeat_form = QFormLayout()
        heartbeat_form.addRow("Heartbeat opacity", self.heartbeat_opacity)
        heartbeat_form.addRow("Heartbeat fade", self.heartbeat_fade)
        layout.addWidget(QLabel("Heartbeat markers"))
        layout.addWidget(self.heartbeat_markers, 1)
        layout.addLayout(heartbeat_form)

        cues = QHBoxLayout()
        dark_widget = QWidget()
        dark_form = QFormLayout(dark_widget)
        self.dark_enabled = QCheckBox("Enable dark cue")
        self.dark_start, self.dark_end, self.dark_fade, self.dark_opacity = _spin(), _spin(), _spin(), _spin(1, 3)
        dark_form.addRow(self.dark_enabled)
        dark_form.addRow("Start", self.dark_start)
        dark_form.addRow("End", self.dark_end)
        dark_form.addRow("Fade out", self.dark_fade)
        dark_form.addRow("Opacity", self.dark_opacity)
        flash_widget = QWidget()
        flash_form = QFormLayout(flash_widget)
        self.flash_enabled = QCheckBox("Enable flash cue")
        self.flash_start, self.flash_duration, self.flash_fade, self.flash_opacity = _spin(), _spin(), _spin(), _spin(1, 3)
        flash_form.addRow(self.flash_enabled)
        flash_form.addRow("Start", self.flash_start)
        flash_form.addRow("Duration", self.flash_duration)
        flash_form.addRow("Fade in", self.flash_fade)
        flash_form.addRow("Opacity", self.flash_opacity)
        cues.addWidget(dark_widget)
        cues.addWidget(flash_widget)
        layout.addLayout(cues)
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
        self.cut_markers.set_values(song.cut_timestamps)
        self.heartbeat_markers.set_values(song.heartbeat.timestamps)
        self.heartbeat_opacity.setValue(song.heartbeat.opacity)
        self.heartbeat_fade.setValue(song.heartbeat.fade_seconds)
        self.dark_enabled.setChecked(song.dark_cue is not None)
        if song.dark_cue:
            self.dark_start.setValue(song.dark_cue.start_seconds)
            self.dark_end.setValue(song.dark_cue.end_seconds)
            self.dark_fade.setValue(song.dark_cue.fade_out_seconds)
            self.dark_opacity.setValue(song.dark_cue.opacity)
        self.flash_enabled.setChecked(song.flash_cue is not None)
        if song.flash_cue:
            self.flash_start.setValue(song.flash_cue.start_seconds)
            self.flash_duration.setValue(song.flash_cue.duration_seconds)
            self.flash_fade.setValue(song.flash_cue.fade_in_seconds)
            self.flash_opacity.setValue(song.flash_cue.opacity)
        self.player.setSource(QUrl.fromLocalFile(str(song.audio_path)))
        self.load_waveform(song.audio_path)
        can_edit = not song.readonly and self.entitlement.has_feature(PRESET_EDITOR_FEATURE)
        self._set_editable(can_edit)
        self.status_label.setText("Built-in preset. Duplicate it to make changes." if song.readonly else "Custom preset")

    def _set_editable(self, editable: bool) -> None:
        controls = [
            self.title_edit, self.artist_edit, self.moods_edit, self.energy_combo, self.bpm_spin, self.audio_edit,
            self.audio_button, self.total_spin, self.minimum_source_spin, self.opening_spin, self.cuts_end_spin,
            self.fade_out_spin, self.escalation_spin, self.transition_spin, self.hard_cut_spin,
            self.short_threshold_spin, self.short_advance_spin, self.cut_markers, self.heartbeat_markers,
            self.heartbeat_opacity, self.heartbeat_fade, self.dark_enabled, self.dark_start, self.dark_end,
            self.dark_fade, self.dark_opacity, self.flash_enabled, self.flash_start, self.flash_duration,
            self.flash_fade, self.flash_opacity,
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
        if not self.current or self.current.readonly:
            return
        timestamp = max(0.0, min(float(timestamp), self.total_spin.value()))
        values = self.cut_markers.values()
        if any(abs(value - timestamp) < 0.0005 for value in values):
            return
        values.append(round(timestamp, 6))
        self.cut_markers.set_values(sorted(values))

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
        dark = None
        if self.dark_enabled.isChecked():
            dark = DarkCue(self.dark_start.value(), self.dark_end.value(), self.dark_fade.value(), self.dark_opacity.value())
        flash = None
        if self.flash_enabled.isChecked():
            flash = FlashCue(self.flash_start.value(), self.flash_duration.value(), self.flash_fade.value(), self.flash_opacity.value())
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
            cut_timestamps=self.cut_markers.values(),
            transitions=TransitionSettings(self.transition_spin.value(), self.hard_cut_spin.value()),
            source_progression=SourceProgressionSettings(self.short_threshold_spin.value(), self.short_advance_spin.value()),
            heartbeat=HeartbeatSettings(self.heartbeat_markers.values(), self.heartbeat_opacity.value(), self.heartbeat_fade.value()),
            dark_cue=dark,
            flash_cue=flash,
            manifest_path=self.current.manifest_path if self.current and not self.current.readonly else None,
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
