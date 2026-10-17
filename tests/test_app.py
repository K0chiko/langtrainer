import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session as DB
from sqlmodel import create_engine, select

from langtrainer import db as dbmodule
from langtrainer.models import Learner, Participant, Session, SessionProgress, Utterance
from langtrainer.web import app as appmodule


@pytest.fixture
def client(monkeypatch, tmp_path):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    monkeypatch.setattr(dbmodule, "_engine", engine)
    monkeypatch.setattr(appmodule.settings, "data_dir", tmp_path)
    started = []
    monkeypatch.setattr(appmodule, "run_session", lambda sid: started.append(("full", sid)))
    monkeypatch.setattr(appmodule, "run_analysis", lambda sid: started.append(("analysis", sid)))
    with TestClient(appmodule.app) as c:
        c.started, c.engine = started, engine
        yield c


def add_session(engine, status, detail="", phase=None, with_text=False):
    with DB(engine) as db:
        learner = db.exec(select(Learner)).first()
        s = Session(learner_id=learner.id, title="t", status=status, status_detail=detail)
        db.add(s)
        db.commit()
        p = Participant(session_id=s.id, role="learner", lang="en", audio_path="x")
        db.add(p)
        db.commit()
        if phase:
            db.add(SessionProgress(session_id=s.id, phase=phase, done=30, total=120))
        if with_text:
            db.add(Utterance(session_id=s.id, participant_id=p.id, start=0, end=1, text="hi"))
        db.commit()
        return s.id


def test_all_pages_render(client):
    for url in ("/", "/progress", "/review", "/errors"):
        assert client.get(url).status_code == 200, url


def test_progress_bar_shown_while_processing(client):
    sid = add_session(client.engine, "transcribing", phase="transcribing")
    page = client.get("/").text
    assert 'class="bar"' in page and "25%" in page
    assert "25%" in client.get(f"/sessions/{sid}").text


def test_no_bar_for_finished_session(client):
    add_session(client.engine, "done")
    assert 'class="bar"' not in client.get("/").text


def test_stale_jobs_are_marked_interrupted_on_startup(monkeypatch, tmp_path):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    monkeypatch.setattr(dbmodule, "_engine", engine)
    monkeypatch.setattr(appmodule.settings, "data_dir", tmp_path)
    dbmodule.init_db()
    sid = add_session(engine, "transcribing", phase="transcribing")
    with TestClient(appmodule.app) as c:
        page = c.get(f"/sessions/{sid}").text
    assert "Interrupted" in page and "/retry" in page


def test_retry_resumes_from_failed_phase(client):
    full = add_session(client.engine, "failed", "interrupted", phase="transcribing")
    analysis = add_session(client.engine, "failed", "boom", phase="analyzing", with_text=True)
    legacy_with_text = add_session(client.engine, "failed", "boom", with_text=True)  # создан до появления прогресса
    legacy_empty = add_session(client.engine, "failed", "boom")
    for sid in (full, analysis, legacy_with_text, legacy_empty):
        assert client.post(f"/sessions/{sid}/retry", follow_redirects=False).status_code == 303
    assert client.started == [
        ("full", full),
        ("analysis", analysis),
        ("analysis", legacy_with_text),
        ("full", legacy_empty),
    ]
    with DB(client.engine) as db:
        assert db.get(Session, full).status == "uploaded"  # повторный клик не запустит дубль


def test_retry_ignored_unless_failed(client):
    sid = add_session(client.engine, "done")
    client.post(f"/sessions/{sid}/retry", follow_redirects=False)
    assert client.started == []
