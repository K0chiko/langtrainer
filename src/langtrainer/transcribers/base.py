from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

# on_progress(сколько секунд аудио уже обработано, длина аудио)
ProgressCallback = Callable[[float, float], None]


@dataclass
class Segment:
    start: float
    end: float
    text: str
    confidence: float  # 0..1


class Transcriber(Protocol):
    def transcribe(self, audio_path: str, lang: str, on_progress: ProgressCallback | None = None) -> list[Segment]: ...
