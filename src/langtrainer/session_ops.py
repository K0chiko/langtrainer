"""Переименование и удаление разговоров."""

import shutil
from dataclasses import dataclass
from pathlib import Path

from sqlmodel import Session as DBSession
from sqlmodel import col, delete, select

from .models import Card, Error, Participant, Review, Session, SessionProgress, Utterance
from .progress import IN_PROGRESS

MAX_TITLE = 200
# У неудавшегося разговора звук тоже можно удалить, но повторить расшифровку после этого нельзя
AUDIO_DELETABLE = ("done", "failed")


class SessionBusy(RuntimeError):
    """Разговор ещё обрабатывается: задачу остановить нельзя, поэтому удалять рано."""


@dataclass
class Impact:
    utterances: int
    errors: int
    cards: int
    reviewed_cards: int  # карточки, по которым уже были повторения: их история тоже пропадёт


def clean_title(title: str) -> str:
    return " ".join(title.split())[:MAX_TITLE]


def rename_session(db: DBSession, session_id: int, title: str) -> bool:
    """Пустое название игнорируется (остаётся прежнее). Возвращает True, если название изменилось."""
    session, title = db.get(Session, session_id), clean_title(title)
    if session is None or not title or title == session.title:
        return False
    session.title = title
    db.add(session)
    db.commit()
    return True


def _ids(db: DBSession, session_id: int) -> tuple[list[int], list[int], list[Card]]:
    utterances = list(db.exec(select(Utterance.id).where(Utterance.session_id == session_id)).all())
    errors = list(db.exec(select(Error.id).where(col(Error.utterance_id).in_(utterances))).all()) if utterances else []
    cards = list(db.exec(select(Card).where(col(Card.error_id).in_(errors))).all()) if errors else []
    return utterances, errors, cards


def deletion_impact(db: DBSession, session_id: int) -> Impact:
    utterances, errors, cards = _ids(db, session_id)
    return Impact(len(utterances), len(errors), len(cards), sum(1 for c in cards if c.reps or c.lapses))


def delete_session(db: DBSession, session_id: int, audio_dir: Path) -> None:
    """Удаляет разговор со всем, что от него зависит: реплики, ошибки, карточки, повторения и аудио."""
    session = db.get(Session, session_id)
    if session is None:
        return
    if session.status in IN_PROGRESS:
        raise SessionBusy(session_id)
    utterances, errors, cards = _ids(db, session_id)
    card_ids = [c.id for c in cards]
    if card_ids:
        db.exec(delete(Review).where(col(Review.card_id).in_(card_ids)))
        db.exec(delete(Card).where(col(Card.id).in_(card_ids)))
    if errors:
        db.exec(delete(Error).where(col(Error.id).in_(errors)))
    if utterances:
        db.exec(delete(Utterance).where(col(Utterance.id).in_(utterances)))
    db.exec(delete(SessionProgress).where(SessionProgress.session_id == session_id))
    db.exec(delete(Participant).where(Participant.session_id == session_id))
    db.delete(session)
    db.commit()
    # Файлы удаляем после базы; только папку этого разговора внутри папки с аудио
    root, folder = audio_dir.resolve(), (audio_dir / str(session_id)).resolve()
    if folder.parent == root and folder.is_dir():
        shutil.rmtree(folder, ignore_errors=True)


class AudioNotDeletable(RuntimeError):
    """Аудио нельзя удалять, пока разговор обрабатывается."""


def delete_audio(db: DBSession, session_id: int, audio_dir: Path) -> int:
    """Удаляет только звук разговора (расшифровка, ошибки и карточки остаются; у неудавшегося разговора пропадёт и возможность повторить расшифровку). Возвращает освобождённые байты."""
    session = db.get(Session, session_id)
    if session is None:
        return 0
    if session.status not in AUDIO_DELETABLE:
        raise AudioNotDeletable(session_id)
    root, folder = audio_dir.resolve(), (audio_dir / str(session_id)).resolve()
    freed = 0
    if folder.parent == root and folder.is_dir():
        freed = sum(f.stat().st_size for f in folder.rglob("*") if f.is_file())
        shutil.rmtree(folder, ignore_errors=True)
    for p in db.exec(select(Participant).where(Participant.session_id == session_id)).all():
        p.audio_path = ""
        db.add(p)
    db.commit()
    return freed
