from collections.abc import Iterator

from sqlmodel import Session as DBSession
from sqlmodel import SQLModel, create_engine, select

from .config import settings
from .models import Learner

_engine = None


def get_engine():
    global _engine
    if _engine is None:
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        settings.audio_dir.mkdir(parents=True, exist_ok=True)
        connect_args = {"check_same_thread": False} if settings.db_url.startswith("sqlite") else {}
        _engine = create_engine(settings.db_url, connect_args=connect_args)
    return _engine


def init_db() -> None:
    SQLModel.metadata.create_all(get_engine())
    with DBSession(get_engine()) as db:
        if db.exec(select(Learner)).first() is None:
            db.add(Learner(name="Me", native_lang="ru", target_lang="en"))
            db.commit()


def get_db() -> Iterator[DBSession]:
    with DBSession(get_engine()) as db:
        yield db
