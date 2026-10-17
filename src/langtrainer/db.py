from collections.abc import Iterator

from sqlalchemy import inspect, text
from sqlmodel import Session as DBSession
from sqlmodel import SQLModel, create_engine, select

from .config import settings
from .models import Learner

_engine = None


def get_engine():
    global _engine
    if _engine is None:
        settings.require_data_dir().mkdir(parents=True, exist_ok=True)
        settings.audio_dir.mkdir(parents=True, exist_ok=True)
        connect_args = {"check_same_thread": False} if settings.db_url.startswith("sqlite") else {}
        _engine = create_engine(settings.db_url, connect_args=connect_args)
    return _engine


# Колонки, добавленные после первых версий: create_all не меняет уже существующие таблицы
_ADDED_COLUMNS = [
    ("card", "easy_streak", "INTEGER NOT NULL DEFAULT 0"),
    ("card", "learned", "BOOLEAN NOT NULL DEFAULT false"),
]


def _add_missing_columns(engine) -> None:
    inspector = inspect(engine)
    with engine.begin() as conn:
        for table, column, ddl in _ADDED_COLUMNS:
            if inspector.has_table(table) and column not in {c["name"] for c in inspector.get_columns(table)}:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))


def init_db() -> None:
    SQLModel.metadata.create_all(get_engine())
    _add_missing_columns(get_engine())
    with DBSession(get_engine()) as db:
        if db.exec(select(Learner)).first() is None:
            db.add(Learner(name="Me", native_lang="ru", target_lang="en"))
            db.commit()


def get_db() -> Iterator[DBSession]:
    with DBSession(get_engine()) as db:
        yield db
