"""Windows call recorder: microphone and system audio (WASAPI loopback) into two mono WAV files.

Needs the `pyaudiowpatch` package (installed automatically on Windows). Written without access to a Windows
machine, so treat it as untested on real hardware until someone confirms it.
"""

import threading
import time
import wave
from pathlib import Path

# A gap shorter than this between expected and actual chunk position is jitter, not silence.
_GAP_TOLERANCE_S = 0.2


def to_mono_int16(data: bytes, channels: int) -> bytes:
    """Average interleaved int16 channels into one."""
    if channels == 1:
        return data
    import numpy as np

    samples = np.frombuffer(data, dtype=np.int16)
    usable = len(samples) - len(samples) % channels
    mixed = samples[:usable].reshape(-1, channels).astype(np.int32).mean(axis=1)
    return mixed.astype(np.int16).tobytes()


class TrackWriter:
    """Writes one mono 16-bit WAV and keeps it aligned with wall-clock time.

    WASAPI loopback delivers no data while nothing is playing, so the system track would otherwise come out
    shorter than the microphone track and every timestamp after a pause would drift. Silence is inserted
    wherever audio is missing, so both tracks of a call share one timeline.
    """

    def __init__(self, path: Path, rate: int, clock=time.monotonic) -> None:
        self._rate = rate
        self._clock = clock
        self._t0 = clock()
        self._frames = 0
        self._lock = threading.Lock()
        self._wav = wave.open(str(path), "wb")
        self._wav.setnchannels(1)
        self._wav.setsampwidth(2)
        self._wav.setframerate(rate)

    def write(self, mono: bytes) -> None:
        with self._lock:
            chunk_frames = len(mono) // 2
            chunk_start = (self._clock() - self._t0) * self._rate - chunk_frames
            gap = int(chunk_start) - self._frames
            if gap > self._rate * _GAP_TOLERANCE_S:
                self._pad(gap)
            self._wav.writeframes(mono)
            self._frames += chunk_frames

    def close(self) -> None:
        with self._lock:
            missing = int((self._clock() - self._t0) * self._rate) - self._frames
            if missing > 0:
                self._pad(missing)
            self._wav.close()

    def _pad(self, frames: int) -> None:
        self._wav.writeframes(b"\x00\x00" * frames)
        self._frames += frames


class WindowsCapture:
    def __init__(self) -> None:
        self._pa = None
        self._streams: list = []
        self._writers: list[TrackWriter] = []
        self._active = False

    @property
    def active(self) -> bool:
        return self._active

    def start(self, files) -> None:
        from .recording import RecorderError

        try:
            import pyaudiowpatch as pyaudio
        except ImportError as exc:
            raise RecorderError("pyaudiowpatch is not installed. Run `uv sync` on Windows.") from exc

        self._pa = pa = pyaudio.PyAudio()
        try:
            mic = self._mic_device(pa)
            loopback = self._loopback_device(pa, pyaudio)
            self._open(pyaudio, mic, files.mic)
            self._open(pyaudio, loopback, files.system)
        except RecorderError:
            self._cleanup()
            raise
        except Exception as exc:  # noqa: BLE001 - PortAudio raises plain OSError/ValueError
            self._cleanup()
            raise RecorderError(f"Could not start recording: {exc}") from exc
        self._active = True

    def stop(self) -> None:
        self._cleanup()

    @staticmethod
    def _mic_device(pa) -> dict:
        from .recording import RecorderError

        try:
            return pa.get_default_input_device_info()
        except (OSError, IOError) as exc:
            raise RecorderError(
                "No microphone found. Check Settings > Privacy & security > Microphone and the default input device."
            ) from exc

    @staticmethod
    def _loopback_device(pa, pyaudio) -> dict:
        from .recording import RecorderError

        try:
            wasapi = pa.get_host_api_info_by_type(pyaudio.paWASAPI)
            speakers = pa.get_device_info_by_index(wasapi["defaultOutputDevice"])
        except (OSError, IOError) as exc:
            raise RecorderError("WASAPI is not available, so system audio cannot be captured.") from exc
        if speakers.get("isLoopbackDevice"):
            return speakers
        for device in pa.get_loopback_device_info_generator():
            if speakers["name"] in device["name"]:
                return device
        raise RecorderError(f"No loopback device found for the default output device '{speakers['name']}'.")

    def _open(self, pyaudio, device: dict, path: Path) -> None:
        channels = max(1, min(2, int(device["maxInputChannels"])))
        rate = int(device["defaultSampleRate"])
        writer = TrackWriter(path, rate)
        self._writers.append(writer)

        def on_audio(data, frame_count, time_info, status):  # noqa: ARG001 - PortAudio callback signature
            writer.write(to_mono_int16(data, channels))
            return (None, pyaudio.paContinue)

        stream = self._pa.open(
            format=pyaudio.paInt16,
            channels=channels,
            rate=rate,
            input=True,
            input_device_index=device["index"],
            frames_per_buffer=rate // 10,
            stream_callback=on_audio,
        )
        self._streams.append(stream)

    def _cleanup(self) -> None:
        for stream in self._streams:
            try:
                stream.stop_stream()
                stream.close()
            except OSError:
                pass
        for writer in self._writers:
            writer.close()
        if self._pa is not None:
            self._pa.terminate()
        self._streams, self._writers, self._pa, self._active = [], [], None, False
