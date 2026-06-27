import subprocess

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QSignalSpy

from e2dm2.waveform import WaveformData, WaveformWidget, extract_waveform


def test_ffmpeg_waveform_extraction_and_cache(tmp_path, monkeypatch):
    audio = tmp_path / "tone.wav"
    subprocess.run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
        "-i", "sine=frequency=440:duration=2", str(audio),
    ], check=True)
    waveform = extract_waveform(audio)
    assert waveform.duration_seconds == 2
    assert 45 <= len(waveform.peaks) <= 55
    assert max(waveform.peaks) > 0.05

    monkeypatch.setattr("e2dm2.waveform.subprocess.run", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("cache missed")))
    cached = extract_waveform(audio)
    assert cached.peaks == pytest.approx(waveform.peaks, abs=0.00001)


def test_waveform_scroll_mapping_and_click_to_add(qtbot):
    widget = WaveformWidget()
    qtbot.addWidget(widget)
    widget.resize(1000, 180)
    widget.set_waveform(WaveformData([0.5] * 2500, 25, 100))
    widget.set_position(50)
    widget.set_window_seconds(40)
    widget.show()
    assert widget.time_at_x(280) == 50
    assert widget.time_at_x(780) == 70

    spy = QSignalSpy(widget.timestamp_clicked)
    qtbot.mouseClick(widget, Qt.MouseButton.LeftButton, pos=QPoint(780, 90))
    assert spy.count() == 1
    assert spy.at(0)[0] == 70


def test_full_song_view_maps_edges(qtbot):
    widget = WaveformWidget()
    qtbot.addWidget(widget)
    widget.resize(800, 180)
    widget.set_waveform(WaveformData([0.25] * 1000, 10, 100))
    widget.set_window_seconds(None)
    assert widget.time_at_x(0) == 0
    assert widget.time_at_x(800) == 100
