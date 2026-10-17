from dataclasses import dataclass
from typing import Protocol


@dataclass
class Segment:
    start: float
    end: float
    text: str
    confidence: float  # 0..1


class Transcriber(Protocol):
    def transcribe(self, audio_path: str, lang: str) -> list[Segment]: ...
