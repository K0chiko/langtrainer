"""Конвейер: аудио -> реплики -> ошибки. Каждый шаг читает и пишет БД, поэтому его можно перезапустить."""

import time
import traceback

from sqlmodel import Session as DBSession
from sqlmodel import col, delete, select

from .analyzers import Finding, LearnerProfile, Line, get_analyzer
from .cards import delete_unreviewed_cards, generate_cards
from .db import get_engine
from .models import Error, Learner, Participant, Session, Utterance
from .progress import audio_duration, set_progress
from .transcribers import get_transcriber


def _set_status(db: DBSession, session: Session, status: str, detail: str = "") -> None:
    session.status, session.status_detail = status, detail
    db.add(session)
    db.commit()


def transcribe_session(db: DBSession, session_id: int) -> None:
    session = db.get(Session, session_id)
    _set_status(db, session, "transcribing")
    # Перезапуск: стираем прежний результат шага и всё, что от него зависит
    old_ids = db.exec(select(Utterance.id).where(Utterance.session_id == session_id)).all()
    if old_ids:
        db.exec(delete(Error).where(col(Error.utterance_id).in_(old_ids)))
        db.exec(delete(Utterance).where(Utterance.session_id == session_id))
        db.commit()
    transcriber = get_transcriber()
    participants = db.exec(select(Participant).where(Participant.session_id == session_id).order_by(Participant.id)).all()
    durations = [audio_duration(p.audio_path) for p in participants]
    total = sum(d or 0.0 for d in durations) if all(durations) else 0.0  # 0 = длина неизвестна
    set_progress(db, session_id, "transcribing", 0, total, restart=True)

    offset = 0.0
    for p, duration in zip(participants, durations):
        last_write = [0.0]

        def report(position: float, track_total: float, _offset: float = offset) -> None:
            now = time.monotonic()
            if now - last_write[0] >= 1.0:  # не чаще раза в секунду
                last_write[0] = now
                set_progress(db, session_id, "transcribing", _offset + min(position, track_total), total)

        for seg in transcriber.transcribe(p.audio_path, p.lang, on_progress=report):
            db.add(
                Utterance(
                    session_id=session_id,
                    participant_id=p.id,
                    start=seg.start,
                    end=seg.end,
                    text=seg.text,
                    asr_confidence=seg.confidence,
                )
            )
        db.commit()
        offset += duration or 0.0
    set_progress(db, session_id, "transcribing", total, total)


def analyze_session(db: DBSession, session_id: int) -> None:
    session = db.get(Session, session_id)
    _set_status(db, session, "analyzing")
    learner = db.get(Learner, session.learner_id)
    roles = {p.id: p.role for p in db.exec(select(Participant).where(Participant.session_id == session_id))}
    utterances = db.exec(
        select(Utterance).where(Utterance.session_id == session_id).order_by(Utterance.start, Utterance.id)
    ).all()
    lines = [Line(u.id, roles[u.participant_id], u.text, u.asr_confidence) for u in utterances]

    # Повторный разбор: старые ошибки заменяются, кроме тех, по чьим карточкам уже шли повторы
    utt_ids = [u.id for u in utterances]
    old_errors = db.exec(select(Error).where(col(Error.utterance_id).in_(utt_ids))).all() if utt_ids else []
    keep = delete_unreviewed_cards(db, [e.id for e in old_errors])
    drop = [e.id for e in old_errors if e.id not in keep]
    if drop:
        db.exec(delete(Error).where(col(Error.id).in_(drop)))
        db.commit()
    kept = {(e.utterance_id, e.original, e.corrected) for e in old_errors if e.id in keep}

    set_progress(db, session_id, "analyzing", 0, 0, restart=True)
    profile = LearnerProfile(learner.native_lang, learner.target_lang, learner.level)
    findings: list[Finding] = get_analyzer().analyze(
        profile, lines, on_progress=lambda done, batches: set_progress(db, session_id, "analyzing", done, batches)
    )
    for f in findings:
        if (f.utterance_id, f.original, f.corrected) in kept:
            continue
        db.add(
            Error(
                utterance_id=f.utterance_id,
                learner_id=learner.id,
                category=f.category,
                original=f.original,
                corrected=f.corrected,
                explanation=f.explanation,
                severity=f.severity,
                rule_key=f.rule_key,
            )
        )
    db.commit()
    generate_cards(db, learner.id)


def _run(session_id: int, steps) -> None:
    """Запуск шагов в фоне; статус и ошибки видны в интерфейсе."""
    with DBSession(get_engine()) as db:
        try:
            for step in steps:
                step(db, session_id)
            _set_status(db, db.get(Session, session_id), "done")
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()
            _set_status(db, db.get(Session, session_id), "failed", f"{type(exc).__name__}: {exc}")


def run_session(session_id: int) -> None:
    _run(session_id, [transcribe_session, analyze_session])


def run_analysis(session_id: int) -> None:
    _run(session_id, [analyze_session])
