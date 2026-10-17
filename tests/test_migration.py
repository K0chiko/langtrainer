from sqlalchemy import inspect, text
from sqlmodel import create_engine

from langtrainer import db as dbmodule


def test_old_card_table_gets_the_new_columns(monkeypatch, tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE card (id INTEGER PRIMARY KEY, front TEXT)"))
        conn.execute(text("INSERT INTO card (id, front) VALUES (1, 'x')"))
    dbmodule._add_missing_columns(engine)
    dbmodule._add_missing_columns(engine)  # idempotent
    assert {"easy_streak", "learned"} <= {c["name"] for c in inspect(engine).get_columns("card")}
    with engine.begin() as conn:
        assert conn.execute(text("SELECT easy_streak, learned FROM card")).one() == (0, 0)
