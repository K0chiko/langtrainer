import sys
import wave

import numpy as np
import pytest

from langtrainer import recording
from langtrainer.recording_windows import TrackWriter, to_mono_int16

RATE = 1000


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def _chunk(seconds: float, value: int = 100) -> bytes:
    return np.full(int(seconds * RATE), value, dtype=np.int16).tobytes()


def _read(path) -> np.ndarray:
    with wave.open(str(path), "rb") as w:
        assert (w.getnchannels(), w.getsampwidth(), w.getframerate()) == (1, 2, RATE)
        return np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)


def test_to_mono_averages_channels():
    stereo = np.array([100, 200, -50, 50], dtype=np.int16).tobytes()
    assert np.frombuffer(to_mono_int16(stereo, 2), dtype=np.int16).tolist() == [150, 0]


def test_to_mono_passes_mono_through():
    data = _chunk(0.1)
    assert to_mono_int16(data, 1) == data


def test_continuous_audio_gets_no_padding(tmp_path):
    clock = FakeClock()
    writer = TrackWriter(tmp_path / "a.wav", RATE, clock)
    for _ in range(5):
        clock.now += 0.1
        writer.write(_chunk(0.1))
    writer.close()
    assert len(_read(tmp_path / "a.wav")) == 500


def test_silence_gap_is_filled_so_tracks_stay_aligned(tmp_path):
    clock = FakeClock()
    writer = TrackWriter(tmp_path / "a.wav", RATE, clock)
    clock.now = 0.1
    writer.write(_chunk(0.1))
    clock.now = 3.1  # nothing was playing for 2.9 s, then 0.1 s of audio arrives
    writer.write(_chunk(0.1))
    writer.close()
    samples = _read(tmp_path / "a.wav")
    assert len(samples) == 3100
    assert (samples[100:3000] == 0).all()
    assert (samples[3000:] == 100).all()


def test_trailing_silence_is_padded_on_close(tmp_path):
    clock = FakeClock()
    writer = TrackWriter(tmp_path / "a.wav", RATE, clock)
    clock.now = 0.5
    writer.write(_chunk(0.5))
    clock.now = 2.0
    writer.close()
    assert len(_read(tmp_path / "a.wav")) == 2000


def test_recorder_rejects_unsupported_os(monkeypatch):
    monkeypatch.setattr(recording.platform, "system", lambda: "Linux")
    with pytest.raises(recording.RecorderError, match="not implemented for Linux"):
        recording._make_capture()


def test_recorder_picks_windows_capture(monkeypatch):
    monkeypatch.setattr(recording.platform, "system", lambda: "Windows")
    from langtrainer.recording_windows import WindowsCapture

    assert isinstance(recording._make_capture(), WindowsCapture)


@pytest.mark.skipif(sys.platform == "win32", reason="pyaudiowpatch is installed on Windows")
def test_windows_capture_reports_missing_dependency():
    from langtrainer.recording_windows import WindowsCapture

    capture = WindowsCapture()
    with pytest.raises(recording.RecorderError, match="pyaudiowpatch"):
        capture.start(recording.RecordedFiles(None, None))
