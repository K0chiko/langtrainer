import math

from .base import Segment


class FasterWhisperTranscriber:
    """Работает на Windows, Linux и macOS (CPU; на Linux/Windows ещё и NVIDIA GPU)."""

    def __init__(self, model_name: str):
        from faster_whisper import WhisperModel

        self._english_only = model_name.endswith(".en")
        self._model = WhisperModel(model_name, device="auto", compute_type="auto")

    def transcribe(self, audio_path: str, lang: str) -> list[Segment]:
        segments, _ = self._model.transcribe(
            audio_path,
            # у моделей *.en параметр language недопустим
            language=None if self._english_only else lang,
            vad_filter=True,
            condition_on_previous_text=False,
        )
        return [
            Segment(s.start, s.end, s.text.strip(), min(1.0, math.exp(s.avg_logprob)))
            for s in segments
            if s.text.strip()
        ]
