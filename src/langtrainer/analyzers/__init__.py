from .base import Analyzer, Finding, LearnerProfile, Line

__all__ = ["Analyzer", "Finding", "LearnerProfile", "Line", "get_analyzer"]


def get_analyzer() -> Analyzer:
    from .llm import LlmAnalyzer

    return LlmAnalyzer()
