"""Прогресс обработки разговора: запись в БД, оценка оставшегося времени, восстановление после остановки."""

from dataclasses import dataclass
from datetime import datetime

from sqlmodel import Session as DBSession
from sqlmodel import select

from .models import Session, SessionProgress, _utcnow

IN_PROGRESS = ("uploaded", "transcribing", "analyzing")
INTERRUPTED = "interrupted"  # значение Session.status_detail; текст подставляет интерфейс

MIN_FRACTION = 0.03  # раньше этого оценка времени слишком скачет
MIN_ELAPSED = 20.0  # секунд


def set_progress(db: DBSession, session_id: int, phase: str, done: float, total: float, *, restart: bool = False) -> None:
    """Записывает прогресс. restart=True начинает новую фазу (сбрасывает отсчёт времени для оценки)."""
    row = db.get(SessionProgress, session_id)
    now = _utcnow()
    if row is None:
        row = SessionProgress(session_id=session_id, phase=phase, phase_started_at=now)
    if restart or row.phase != phase:
        row.phase_started_at = now
    row.phase, row.done, row.total, row.updated_at = phase, done, total, now
    db.add(row)
    db.commit()


def eta_seconds(done: float, total: float, started_at: datetime, now: datetime) -> float | None:
    """Сколько секунд осталось, если скорость не изменится. None, пока данных мало."""
    if total <= 0 or done <= 0:
        return None
    fraction = min(done / total, 1.0)
    elapsed = (now - started_at).total_seconds()
    if fraction < MIN_FRACTION or elapsed < MIN_ELAPSED:
        return None
    return elapsed * (1 - fraction) / fraction


@dataclass
class JobView:
    phase: str
    percent: int | None  # None = объём неизвестен
    eta: float | None  # секунды


def job_view(row: SessionProgress | None, status: str, now: datetime | None = None) -> JobView | None:
    """Что показать пользователю. None, если разговор не в обработке."""
    if status not in IN_PROGRESS:
        return None
    if row is None or not row.phase:
        return JobView(status, None, None)
    now = now or _utcnow()
    percent = min(100, int(row.done * 100 / row.total)) if row.total > 0 else None
    return JobView(row.phase, percent, eta_seconds(row.done, row.total, row.phase_started_at, now))


def mark_interrupted(db: DBSession) -> int:
    """Вызывается при старте сервера: задачи живут внутри процесса, так что «в обработке» после запуска значит «оборвано»."""
    stuck = db.exec(select(Session).where(Session.status.in_(IN_PROGRESS))).all()  # type: ignore[attr-defined]
    for s in stuck:
        s.status, s.status_detail = "failed", INTERRUPTED
        db.add(s)
    db.commit()
    return len(stuck)


def audio_duration(path: str) -> float | None:
    """Длина аудиофайла в секундах без декодирования. None, если прочитать не удалось."""
    try:
        import av

        with av.open(path) as container:
            if container.duration:
                return container.duration / 1_000_000
            stream = container.streams.audio[0]
            if stream.duration and stream.time_base:
                return float(stream.duration * stream.time_base)
    except Exception:  # noqa: BLE001
        return None
    return None
