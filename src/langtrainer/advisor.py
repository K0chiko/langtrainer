"""Персональные советы по слабым местам: берём самые частые ошибки и просим Claude объяснить, что с ними делать."""

import json

from sqlmodel import Session as DBSession
from sqlmodel import select

from .llm import ask_json
from .config import settings
from .models import Insight, Learner
from .stats import WeakSpot, weak_spots

LANG_NAMES = {"en": "English", "ru": "Russian"}

SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "tips": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "rule_key": {"type": "string"},
                    "title": {"type": "string"},
                    "advice": {"type": "string"},
                    "practice": {"type": "string"},
                },
                "required": ["rule_key", "title", "advice", "practice"],
            },
        },
    },
    "required": ["summary", "tips"],
}


def _prompt(learner: Learner, spots: list[WeakSpot]) -> str:
    target, native = LANG_NAMES.get(learner.target_lang, learner.target_lang), LANG_NAMES.get(learner.native_lang, learner.native_lang)
    lines = []
    for s in spots:
        ex = "; ".join(f'"{w}" -> "{r}"' for w, r in s.examples)
        lines.append(f"- {s.rule}: {s.count} mistakes ({s.recent} in the last 14 days). Examples: {ex}")
    return f"""You are a {target} teacher coaching a {native}-speaking learner{f' (level about {learner.level})' if learner.level else ''} after analysing their real conversations.

Their most frequent mistakes, most frequent first:
{chr(10).join(lines)}

Write in {native}:
- summary: 2 sentences about the overall picture and what to focus on first.
- tips: one tip per mistake type above, in the same order. For each:
  - rule_key: copied exactly from the list
  - title: short name of the topic
  - advice: 2-4 sentences: the rule in plain words, and why a {native} speaker tends to make this mistake. Be concrete, use the learner's own examples.
  - practice: one small exercise they can do in their next conversation (a single sentence).
Do not be generic and do not praise excessively."""


def generate_advice(db: DBSession, learner_id: int) -> Insight | None:
    """Создаёт и сохраняет новые советы. Возвращает None, если ошибок ещё нет."""
    learner = db.get(Learner, learner_id)
    spots = weak_spots(db, learner_id, limit=5)
    if not spots:
        return None
    data = ask_json(_prompt(learner, spots), SCHEMA)
    insight = Insight(learner_id=learner_id, based_on_errors=sum(s.count for s in spots), data=json.dumps(data, ensure_ascii=False))
    db.add(insight)
    db.commit()
    db.refresh(insight)
    return insight


def latest_advice(db: DBSession, learner_id: int) -> tuple[Insight, dict] | None:
    insight = db.exec(select(Insight).where(Insight.learner_id == learner_id).order_by(Insight.id.desc())).first()
    return (insight, json.loads(insight.data)) if insight else None
