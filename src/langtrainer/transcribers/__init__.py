import shutil
from functools import lru_cache

from ..config import settings
from .base import Segment, Transcriber

__all__ = ["Segment", "Transcriber", "get_transcriber"]


@lru_cache(maxsize=1)
def get_transcriber() -> Transcriber:
    # "auto" = faster-whisper: работает на любой ОС и не требует установленного ffmpeg.
    # mlx быстрее на Apple Silicon, но включается вручную (LT_TRANSCRIBER=mlx) и требует ffmpeg в PATH.
    choice = "faster-whisper" if settings.transcriber == "auto" else settings.transcriber
    if choice == "mlx":
        if shutil.which("ffmpeg") is None:
            raise RuntimeError("The mlx transcriber needs ffmpeg in PATH. Install it or use LT_TRANSCRIBER=faster-whisper.")
        from .mlx import MlxTranscriber

        return MlxTranscriber(settings.whisper_model)
    if choice == "faster-whisper":
        from .faster_whisper import FasterWhisperTranscriber

        return FasterWhisperTranscriber(settings.whisper_model)
    raise ValueError(f"Unknown transcriber: {choice}")
