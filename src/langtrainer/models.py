from datetime import datetime, timezone

from sqlmodel import Field, SQLModel


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Learner(SQLModel, table=True):
    """Кто учится. Языки задаются здесь, а не в коде: зеркальный режим = второй Learner."""

    id: int | None = Field(default=None, primary_key=True)
    name: str
    native_lang: str = "ru"
    target_lang: str = "en"
    level: str = ""  # CEFR, например "B1"; пусто = неизвестно


class Session(SQLModel, table=True):
    """Один разговор."""

    id: int | None = Field(default=None, primary_key=True)
    learner_id: int = Field(foreign_key="learner.id", index=True)
    title: str = ""
    created_at: datetime = Field(default_factory=_now)
    # uploaded -> transcribing -> analyzing -> done | failed
    status: str = "uploaded"
    status_detail: str = ""


class Participant(SQLModel, table=True):
    """Участник сессии и его аудиодорожка."""

    id: int | None = Field(default=None, primary_key=True)
    session_id: int = Field(foreign_key="session.id", index=True)
    role: str  # "learner" | "partner"
    lang: str  # на каком языке говорит (для learner это его target_lang)
    audio_path: str


class Utterance(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    session_id: int = Field(foreign_key="session.id", index=True)
    participant_id: int = Field(foreign_key="participant.id", index=True)
    start: float
    end: float
    text: str
    # 0..1; низкое значение = ASR мог ошибиться, а не говорящий
    asr_confidence: float = 1.0


class Error(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    utterance_id: int = Field(foreign_key="utterance.id", index=True)
    learner_id: int = Field(foreign_key="learner.id", index=True)
    category: str  # grammar | vocabulary | preposition | article | word_order | tense | unnatural
    original: str
    corrected: str
    explanation: str
    severity: int = 2  # 1 мелочь, 2 заметно, 3 мешает понять
    # Короткий идентификатор правила/темы, например "articles.missing". Позже станет внешним ключом на таблицу Rule.
    rule_key: str = Field(default="", index=True)
    # Пользователь отклонил ложное срабатывание: такие ошибки не попадают в карточки
    dismissed: bool = False
    created_at: datetime = Field(default_factory=_now)


def _utcnow() -> datetime:
    """Текущее время в UTC с часовым поясом (SQLModel требует aware-даты)."""
    return datetime.now(timezone.utc)


class Card(SQLModel, table=True):
    """Карточка повторения. Одна карточка на ошибку; расписание по упрощённой схеме SM-2."""

    id: int | None = Field(default=None, primary_key=True)
    learner_id: int = Field(foreign_key="learner.id", index=True)
    error_id: int = Field(foreign_key="error.id", unique=True)
    kind: str = "fix"  # fix = исправь фразу; позже: cloze, translate
    front: str
    back: str
    explanation: str = ""
    created_at: datetime = Field(default_factory=_utcnow)
    due: datetime = Field(default_factory=_utcnow, index=True)
    interval_days: float = 0.0
    ease: float = 2.5
    reps: int = 0
    lapses: int = 0
    suspended: bool = False  # ошибку отклонили как ложную


class Review(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    card_id: int = Field(foreign_key="card.id", index=True)
    rating: int  # 1 снова, 2 трудно, 3 хорошо, 4 легко
    reviewed_at: datetime = Field(default_factory=_utcnow)
    interval_after_days: float = 0.0


class Insight(SQLModel, table=True):
    """Сгенерированные советы по слабым местам. Хранится JSON: {"summary": ..., "tips": [...]}."""

    id: int | None = Field(default=None, primary_key=True)
    learner_id: int = Field(foreign_key="learner.id", index=True)
    created_at: datetime = Field(default_factory=_utcnow)
    based_on_errors: int = 0
    data: str
