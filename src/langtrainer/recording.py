"""Call recording: microphone and system audio into two separate WAV tracks.

macOS uses the Swift helper recorder/macos/ltrecord; Windows captures in-process (recording_windows.py).
"""

import platform
import shutil
import signal
import subprocess
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .config import settings

_MAC_DIR = Path(__file__).resolve().parents[2] / "recorder" / "macos"


@dataclass
class RecordedFiles:
    mic: Path
    system: Path


class RecorderError(RuntimeError):
    pass


class MacCapture:
    def __init__(self) -> None:
        self._proc: subprocess.Popen | None = None

    @property
    def active(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def start(self, files: RecordedFiles) -> None:
        proc = subprocess.Popen(
            [str(self._binary()), str(files.mic), str(files.system)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        ready = threading.Event()

        def wait_ready() -> None:
            if proc.stdout and proc.stdout.readline().strip() == "READY":
                ready.set()

        threading.Thread(target=wait_ready, daemon=True).start()
        if not ready.wait(timeout=15):
            proc.kill()
            err = proc.stderr.read().strip() if proc.stderr else ""
            raise RecorderError(
                (err or "The recorder did not start.")
                + " Check System Settings > Privacy & Security: Screen & System Audio Recording and Microphone."
            )
        self._proc = proc

    def stop(self) -> None:
        self._proc.send_signal(signal.SIGINT)
        try:
            self._proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            self._proc.kill()
            raise RecorderError("The recorder did not stop in time; files may be incomplete.")
        self._proc = None

    @staticmethod
    def _binary() -> Path:
        binary = _MAC_DIR / "ltrecord"
        if not binary.exists():
            if shutil.which("swiftc") is None:
                raise RecorderError("swiftc not found. Install Xcode Command Line Tools: xcode-select --install")
            result = subprocess.run(
                ["swiftc", "-O", "-swift-version", "5", str(_MAC_DIR / "ltrecord.swift"), "-o", str(binary)],
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                raise RecorderError(f"Could not build the recorder: {result.stderr.strip()}")
        return binary


def _make_capture():
    system = platform.system()
    if system == "Darwin":
        return MacCapture()
    if system == "Windows":
        from .recording_windows import WindowsCapture

        return WindowsCapture()
    raise RecorderError(f"Recording is not implemented for {system} yet. Upload files instead.")


class Recorder:
    def __init__(self) -> None:
        self._capture = None
        self._files: RecordedFiles | None = None
        self._started_at: datetime | None = None
        self._lock = threading.Lock()

    @property
    def active(self) -> bool:
        return self._capture is not None and self._capture.active

    @property
    def started_at(self) -> datetime | None:
        return self._started_at if self.active else None

    def start(self) -> None:
        with self._lock:
            if self.active:
                raise RecorderError("Recording is already running.")
            capture = _make_capture()
            folder = settings.audio_dir / "_recording"
            folder.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            files = RecordedFiles(folder / f"{stamp}-me.wav", folder / f"{stamp}-partner.wav")
            capture.start(files)
            self._capture, self._files, self._started_at = capture, files, datetime.now()

    def stop(self) -> RecordedFiles:
        with self._lock:
            if not self.active or self._files is None:
                raise RecorderError("No recording is running.")
            self._capture.stop()
            files, self._capture, self._files, self._started_at = self._files, None, None, None
            return files


recorder = Recorder()
