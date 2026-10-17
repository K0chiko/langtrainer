from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

# on_progress(сколько пакетов готово, сколько всего)
ProgressCallback = Callable[[int, int], None]

CATEGORIES = ["grammar", "vocabulary", "preposition", "article", "word_order", "tense", "unnatural"]


@dataclass
class Line:
    """Реплика в контексте разговора."""

    utterance_id: int
    role: str  # "learner" | "partner"
    text: str
    confidence: float


@dataclass
class LearnerProfile:
    native_lang: str
    target_lang: str
    level: str = ""


@dataclass
class Finding:
    utterance_id: int
    category: str
    original: str
    corrected: str
    explanation: str
    severity: int
    rule_key: str


class Analyzer(Protocol):
    def analyze(
        self, profile: LearnerProfile, lines: list[Line], on_progress: ProgressCallback | None = None
    ) -> list[Finding]:
        """Найти ошибки в репликах с role == "learner". Реплики partner даны только как контекст."""
        ...
