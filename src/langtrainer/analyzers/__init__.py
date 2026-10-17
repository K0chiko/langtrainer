from ..config import settings
from .base import Analyzer, Finding, LearnerProfile, Line

__all__ = ["Analyzer", "Finding", "LearnerProfile", "Line", "get_analyzer"]


def get_analyzer() -> Analyzer:
    if settings.analyzer == "claude-cli":
        from .claude_cli import ClaudeCliAnalyzer

        return ClaudeCliAnalyzer()
    raise ValueError(f"Unknown analyzer: {settings.analyzer}")
