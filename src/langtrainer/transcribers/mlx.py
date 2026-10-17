import math

from .base import ProgressCallback, Segment

# Модели mlx-whisper лежат на Hugging Face под такими именами
_REPOS = {
    "tiny": "mlx-community/whisper-tiny-mlx",
    "base": "mlx-community/whisper-base-mlx",
    "small": "mlx-community/whisper-small-mlx",
    "medium": "mlx-community/whisper-medium-mlx",
    "large-v3": "mlx-community/whisper-large-v3-mlx",
    "large-v3-turbo": "mlx-community/whisper-large-v3-turbo",
}


class MlxTranscriber:
    """Только macOS на Apple Silicon. Ставится отдельно: uv sync --extra mlx"""

    def __init__(self, model_name: str):
        import mlx_whisper  # noqa: F401  (проверяем, что установлен)

        self._repo = _REPOS.get(model_name, model_name)

    def transcribe(self, audio_path: str, lang: str, on_progress: ProgressCallback | None = None) -> list[Segment]:
        # mlx-whisper отдаёт результат только целиком, поэтому прогресс по ходу дела недоступен
        import mlx_whisper

        result = mlx_whisper.transcribe(
            audio_path,
            path_or_hf_repo=self._repo,
            language=lang,
            condition_on_previous_text=False,
        )
        return [
            Segment(s["start"], s["end"], s["text"].strip(), min(1.0, math.exp(s.get("avg_logprob", 0.0))))
            for s in result["segments"]
            if s["text"].strip()
        ]
