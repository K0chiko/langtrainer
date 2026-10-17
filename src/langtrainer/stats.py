"""Статистика по ошибкам, разговорам и повторениям. Только чтение из БД."""

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlmodel import Session as DBSession
from sqlmodel import select

from .models import Card, Error, Participant, Review, Session, Utterance, _utcnow

RECENT_DAYS = 14


@dataclass
class WeakSpot:
    rule: str
    count: int
    recent: int  # за последние RECENT_DAYS дней
    explanation: str
    examples: list[tuple[str, str]] = field(default_factory=list)  # (неверно, верно), от новых к старым


@dataclass
class SessionPoint:
    session_id: int
    title: str
    date: datetime
    words: int
    errors: int

    @property
    def per100(self) -> float:
        return round(self.errors * 100 / self.words, 1) if self.words else 0.0


def _active_errors(db: DBSession, learner_id: int) -> list[Error]:
    return list(
        db.exec(
            select(Error).where(Error.learner_id == learner_id, Error.dismissed == False).order_by(Error.id.desc())  # noqa: E712
        ).all()
    )


def weak_spots(db: DBSession, learner_id: int, limit: int = 10, now: datetime | None = None) -> list[WeakSpot]:
    now = now or _utcnow()
    since = now - timedelta(days=RECENT_DAYS)
    spots: dict[str, WeakSpot] = {}
    for e in _active_errors(db, learner_id):  # от новых к старым
        key = e.rule_key or e.category
        spot = spots.setdefault(key, WeakSpot(key, 0, 0, e.explanation))
        spot.count += 1
        if e.created_at >= since:
            spot.recent += 1
        if len(spot.examples) < 3:
            spot.examples.append((e.original, e.corrected))
    return sorted(spots.values(), key=lambda s: (-s.count, s.rule))[:limit]


def category_counts(db: DBSession, learner_id: int) -> list[tuple[str, int]]:
    counts: dict[str, int] = {}
    for e in _active_errors(db, learner_id):
        counts[e.category] = counts.get(e.category, 0) + 1
    return sorted(counts.items(), key=lambda kv: -kv[1])


def session_series(db: DBSession, learner_id: int) -> list[SessionPoint]:
    """Ошибки на 100 слов в каждом разговоре, от старых к новым. Слова считаются только в репликах ученика."""
    errors_by_utt: dict[int, int] = {}
    for e in _active_errors(db, learner_id):
        errors_by_utt[e.utterance_id] = errors_by_utt.get(e.utterance_id, 0) + 1
    points = []
    for s in db.exec(select(Session).where(Session.learner_id == learner_id, Session.status == "done").order_by(Session.created_at)):
        learner_parts = {p.id for p in db.exec(select(Participant).where(Participant.session_id == s.id, Participant.role == "learner"))}
        utts = [u for u in db.exec(select(Utterance).where(Utterance.session_id == s.id)) if u.participant_id in learner_parts]
        words = sum(len(u.text.split()) for u in utts)
        errors = sum(errors_by_utt.get(u.id, 0) for u in utts)
        points.append(SessionPoint(s.id, s.title, s.created_at, words, errors))
    return points


@dataclass
class ReviewStats:
    cards: int
    due: int
    reviews_7d: int
    recalled_7d: int  # оценки «Вспомнил» и «Легко»

    @property
    def retention_pct(self) -> int | None:
        return round(self.recalled_7d * 100 / self.reviews_7d) if self.reviews_7d else None


def review_stats(db: DBSession, learner_id: int, now: datetime | None = None) -> ReviewStats:
    now = now or _utcnow()
    cards = db.exec(select(Card).where(Card.learner_id == learner_id, Card.suspended == False)).all()  # noqa: E712
    ids = {c.id for c in cards}
    recent = [r for r in db.exec(select(Review).where(Review.reviewed_at >= now - timedelta(days=7))) if r.card_id in ids]
    return ReviewStats(
        cards=len(cards),
        due=sum(1 for c in cards if c.due <= now),
        reviews_7d=len(recent),
        recalled_7d=sum(1 for r in recent if r.rating >= 3),
    )
