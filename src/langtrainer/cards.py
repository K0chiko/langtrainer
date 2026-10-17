"""Карточки из ошибок и повторение."""

from sqlmodel import Session as DBSession
from sqlmodel import col, delete, func, select

from . import srs
from .models import Card, Error, Review, Utterance, _utcnow


def _key(e: Error) -> tuple[str, str]:
    return e.original.strip().lower(), e.corrected.strip().lower()


def generate_cards(db: DBSession, learner_id: int) -> int:
    """Создаёт карточки для ошибок, у которых их ещё нет. Идемпотентно. Возвращает число новых карточек."""
    have = set(db.exec(select(Card.error_id)).all())
    seen = {_key(e) for e in db.exec(select(Error).where(col(Error.id).in_(have))).all()} if have else set()
    created = 0
    errors = db.exec(
        select(Error).where(Error.learner_id == learner_id, Error.dismissed == False).order_by(Error.id)  # noqa: E712
    ).all()
    for e in errors:
        if e.id in have or _key(e) in seen:
            continue
        utt = db.get(Utterance, e.utterance_id)
        sentence = utt.text if utt else e.original
        fixed = sentence.replace(e.original, e.corrected, 1) if e.original in sentence else e.corrected
        db.add(Card(learner_id=learner_id, error_id=e.id, front=sentence, back=fixed, explanation=e.explanation))
        seen.add(_key(e))
        created += 1
    db.commit()
    return created


def set_suspended(db: DBSession, error_id: int, suspended: bool) -> None:
    card = db.exec(select(Card).where(Card.error_id == error_id)).first()
    if card is not None:
        card.suspended = suspended
        db.add(card)
        db.commit()


def delete_unreviewed_cards(db: DBSession, error_ids: list[int]) -> set[int]:
    """Удаляет карточки без повторов для этих ошибок. Возвращает id ошибок, чьи карточки уже повторялись (их трогать нельзя)."""
    if not error_ids:
        return set()
    cards = db.exec(select(Card).where(col(Card.error_id).in_(error_ids))).all()
    reviewed = {c.error_id for c in cards if c.reps > 0 or c.lapses > 0}
    drop = [c.id for c in cards if c.error_id not in reviewed]
    if drop:
        db.exec(delete(Review).where(col(Review.card_id).in_(drop)))
        db.exec(delete(Card).where(col(Card.id).in_(drop)))
        db.commit()
    return reviewed


def next_due(db: DBSession, learner_id: int) -> Card | None:
    return db.exec(
        select(Card)
        .where(Card.learner_id == learner_id, Card.suspended == False, Card.due <= _utcnow())  # noqa: E712
        .order_by(Card.due)
    ).first()


def due_count(db: DBSession, learner_id: int) -> int:
    return db.exec(
        select(func.count())
        .select_from(Card)
        .where(Card.learner_id == learner_id, Card.suspended == False, Card.due <= _utcnow())  # noqa: E712
    ).one()


def review(db: DBSession, card_id: int, rating: int) -> None:
    card = db.get(Card, card_id)
    now = _utcnow()
    new = srs.schedule(srs.State(card.interval_days, card.ease, card.reps, card.lapses, card.due), rating, now)
    card.interval_days, card.ease, card.reps, card.lapses, card.due = (
        new.interval_days,
        new.ease,
        new.reps,
        new.lapses,
        new.due,
    )
    db.add(card)
    db.add(Review(card_id=card.id, rating=rating, reviewed_at=now, interval_after_days=new.interval_days))
    db.commit()


def format_wait(due, now) -> tuple[str, int]:
    """Когда вернётся карточка, как (ключ перевода wait.*, число); текст подставляет интерфейс."""
    minutes = round((due - now).total_seconds() / 60)
    if minutes < 60:
        return "minutes", minutes
    days = round(minutes / 1440)
    if days < 1:
        return "hours", 0
    if days < 30:
        return "days", days
    return "months", round(days / 30)


def rating_options(card: Card) -> list[tuple[int, str, tuple[str, int]]]:
    """Для каждой оценки: (оценка, ключ перевода подписи rate.*, когда вернётся карточка)."""
    now = _utcnow()
    state = srs.State(card.interval_days, card.ease, card.reps, card.lapses, card.due)
    return [(r, f"rate.{r}", format_wait(srs.schedule(state, r, now).due, now)) for r in (1, 2, 3, 4)]
