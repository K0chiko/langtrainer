from ..llm import ask_json
from ..config import settings
from .base import CATEGORIES, Finding, LearnerProfile, Line, ProgressCallback

LANG_NAMES = {"en": "English", "ru": "Russian"}

SCHEMA = {
    "type": "object",
    "properties": {
        "errors": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "utterance_id": {"type": "integer"},
                    "category": {"type": "string", "enum": CATEGORIES},
                    "original": {"type": "string"},
                    "corrected": {"type": "string"},
                    "explanation": {"type": "string"},
                    "severity": {"type": "integer", "enum": [1, 2, 3]},
                    "rule_key": {"type": "string"},
                },
                "required": [
                    "utterance_id",
                    "category",
                    "original",
                    "corrected",
                    "explanation",
                    "severity",
                    "rule_key",
                ],
            },
        }
    },
    "required": ["errors"],
}

CONTEXT_LINES = 6  # сколько предыдущих реплик показывать как контекст


def _lang(code: str) -> str:
    return LANG_NAMES.get(code, code)


class LlmAnalyzer:
    """Анализ через языковую модель; провайдер выбирается в llm.py (Claude CLI, OpenAI-совместимый сервер, Anthropic API)."""

    def analyze(
        self, profile: LearnerProfile, lines: list[Line], on_progress: ProgressCallback | None = None
    ) -> list[Finding]:
        learner_idx = [i for i, ln in enumerate(lines) if ln.role == "learner"]
        findings: list[Finding] = []
        size = settings.analyze_batch_size
        batches = [learner_idx[b : b + size] for b in range(0, len(learner_idx), size)]
        if on_progress:
            on_progress(0, len(batches))
        for n, chunk in enumerate(batches, start=1):
            lo = max(0, chunk[0] - CONTEXT_LINES)
            window = lines[lo : chunk[-1] + 1]
            valid_ids = {lines[i].utterance_id for i in chunk}
            for f in self._ask(profile, window):
                if f.utterance_id in valid_ids and f.original.strip() and f.original != f.corrected:
                    findings.append(f)
            if on_progress:
                on_progress(n, len(batches))
        return findings

    def _prompt(self, profile: LearnerProfile, window: list[Line]) -> str:
        target, native = _lang(profile.target_lang), _lang(profile.native_lang)
        level = f" (level about {profile.level})" if profile.level else ""
        transcript = "\n".join(
            f"[{ln.utterance_id}] {'LEARNER' if ln.role == 'learner' else 'PARTNER'}"
            f"{' (low ASR confidence)' if ln.confidence < 0.6 else ''}: {ln.text}"
            for ln in window
        )
        return f"""You are a careful {target} teacher analysing a transcript of a real conversation between a learner ({native} native speaker{level}) and a native {target} speaker (PARTNER).

Find mistakes ONLY in LEARNER lines. PARTNER lines are context only.

The text comes from speech recognition, so:
- Ignore punctuation, capitalisation, fillers (um, uh), false starts, repetitions, and normal informal spoken forms (gonna, kinda, contractions).
- Lines marked "low ASR confidence" may contain recognition errors: report a mistake there only if it is clearly a learner mistake (typical for {native} speakers), not a plausible mishearing.
- Do not invent mistakes. If a sentence is acceptable in natural speech, leave it alone. It is fine to return no errors.
- Report real grammar, vocabulary choice, prepositions, articles, word order, tense, and phrases that are understandable but unnatural.

For each mistake give:
- utterance_id: the number in square brackets
- category: one of {', '.join(CATEGORIES)}
- original: the exact wrong fragment copied from the line (short, not the whole line unless needed)
- corrected: how a native speaker would say that fragment
- explanation: 1-2 short sentences in {native} explaining the rule or why it sounds wrong
- severity: 1 minor, 2 noticeable, 3 hinders understanding
- rule_key: a short stable lowercase id of the underlying rule, like "article.missing", "tense.present_perfect", "preposition.depend_on". Reuse the same id for the same kind of mistake.

Transcript:
{transcript}
"""

    def _ask(self, profile: LearnerProfile, window: list[Line]) -> list[Finding]:
        data = ask_json(self._prompt(profile, window), SCHEMA)
        return [
            Finding(
                utterance_id=e["utterance_id"],
                category=e["category"],
                original=e["original"],
                corrected=e["corrected"],
                explanation=e["explanation"],
                severity=e["severity"],
                rule_key=e["rule_key"].strip().lower(),
            )
            for e in data["errors"]
        ]
