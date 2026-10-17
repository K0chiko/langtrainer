import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session as DB
from sqlmodel import create_engine, select

from langtrainer import db as dbmodule
from langtrainer import storage
from langtrainer.models import Learner, Participant, Session, Utterance
from langtrainer.web import app as appmodule


@pytest.fixture
def fresh(monkeypatch, tmp_path):
    """App state as on a first launch: no data folder chosen, config in a temp profile."""
    monkeypatch.setenv("LT_CONFIG_DIR", str(tmp_path / "profile"))
    monkeypatch.setattr(storage.settings, "data_dir", None)
    monkeypatch.setattr(storage, "_source", "")
    monkeypatch.setattr(dbmodule, "_engine", None)
    return tmp_path


def test_format_size():
    assert storage.format_size(0) == "0 B"
    assert storage.format_size(1536) == "1.5 KB"
    assert storage.format_size(5 * 1024**2) == "5.0 MB"


def test_validate_creates_folder_and_rejects_bad_input(tmp_path):
    target = tmp_path / "a" / "b"
    assert storage.validate_folder(f'  "{target}" ') == target.resolve()
    assert target.is_dir()
    with pytest.raises(storage.StorageError) as exc:
        storage.validate_folder("   ")
    assert exc.value.code == "empty"
    (tmp_path / "file.txt").write_text("x")
    with pytest.raises(storage.StorageError) as exc:
        storage.validate_folder(str(tmp_path / "file.txt"))
    assert exc.value.code == "not_dir"


def test_saved_choice_round_trip(fresh):
    assert storage.load_saved_data_dir() is None
    chosen = storage.choose_data_dir(str(fresh / "mydata"))
    assert json.loads(storage.config_file().read_text())["data_dir"] == str(chosen)
    assert storage.load_saved_data_dir() == chosen
    assert storage.source() == "app"


def test_environment_setting_beats_saved_choice(fresh):
    storage.save_data_dir(fresh / "saved")
    storage.settings.data_dir = fresh / "from-env"
    storage.apply_saved()
    assert storage.settings.data_dir == fresh / "from-env"
    assert storage.source() == "environment"


def test_saved_choice_is_applied_when_nothing_else_is_set(fresh):
    storage.save_data_dir(fresh / "saved")
    storage.apply_saved()
    assert storage.settings.data_dir == fresh / "saved"
    assert storage.source() == "app"


def test_suggestions_include_existing_data_next_to_the_app(fresh, monkeypatch):
    monkeypatch.chdir(fresh)
    assert [k for k, _ in storage.suggested_folders()] == ["default"]
    (fresh / "data").mkdir()
    (fresh / "data" / storage.DB_FILE).write_text("")
    kinds = [k for k, _ in storage.suggested_folders()]
    assert kinds == ["existing", "default"]


def test_usage_counts_per_session(tmp_path):
    (tmp_path / "audio" / "3").mkdir(parents=True)
    (tmp_path / "audio" / "3" / "me.wav").write_bytes(b"x" * 100)
    (tmp_path / "audio" / "_recording").mkdir()
    (tmp_path / "audio" / "_recording" / "a.wav").write_bytes(b"x" * 40)
    (tmp_path / storage.DB_FILE).write_bytes(b"x" * 10)
    used = storage.usage(tmp_path)
    assert (used.database, used.audio, used.per_session) == (10, 140, {3: 100})


@pytest.fixture
def client(fresh, monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    monkeypatch.setattr(dbmodule, "_engine", engine)
    with TestClient(appmodule.app) as c:
        c.engine, c.base = engine, fresh
        yield c


def test_everything_redirects_to_setup_until_a_folder_is_chosen(client):
    for url in ("/", "/progress", "/storage"):
        r = client.get(url, follow_redirects=False)
        assert (r.status_code, r.headers["location"]) == (303, "/setup"), url
    assert client.get("/setup").status_code == 200
    assert client.get("/lang/ru", follow_redirects=False).status_code == 303


def test_setup_form_is_translated_and_has_no_nav_database_access(client):
    page = client.get("/setup", headers={"Accept-Language": "ru"}).text
    assert "Где приложению хранить данные?" in page


def test_choosing_a_folder_completes_setup(client):
    folder = client.base / "chosen"
    r = client.post("/setup", data={"folder": str(folder)}, follow_redirects=False)
    assert (r.status_code, r.headers["location"]) == (303, "/")
    assert folder.is_dir()
    assert client.get("/").status_code == 200
    assert client.get("/setup", follow_redirects=False).status_code == 303  # already configured
    page = client.get("/storage").text
    assert str(folder.resolve()) in page


def test_invalid_folder_shows_an_error_and_keeps_the_input(client):
    r = client.post("/setup", data={"folder": "  "})
    assert r.status_code == 200 and "Enter a folder path." in r.text
    assert storage.needs_setup()


def configured(client, status="done"):
    client.post("/setup", data={"folder": str(client.base / "data")})
    with DB(client.engine) as db:
        learner = db.exec(select(Learner)).first()
        s = Session(learner_id=learner.id, title="call", status=status)
        db.add(s)
        db.commit()
        folder = client.base / "data" / "audio" / str(s.id)
        folder.mkdir(parents=True)
        (folder / "me.wav").write_bytes(b"x" * 2048)
        p = Participant(session_id=s.id, role="learner", lang="en", audio_path=str(folder / "me.wav"))
        db.add(p)
        db.commit()
        db.add(Utterance(session_id=s.id, participant_id=p.id, start=0, end=1, text="hello"))
        db.commit()
        return s.id, folder


def test_delete_audio_keeps_the_transcript(client):
    sid, folder = configured(client)
    assert "Delete audio (2.0 KB)" in client.get(f"/sessions/{sid}").text
    r = client.post(f"/sessions/{sid}/delete-audio", follow_redirects=False)
    assert r.status_code == 303
    assert not folder.exists()
    with DB(client.engine) as db:
        assert db.exec(select(Participant)).first().audio_path == ""
        assert db.exec(select(Utterance)).first().text == "hello"
    assert "Delete audio" not in client.get(f"/sessions/{sid}").text


def test_storage_page_lists_sessions_by_size(client):
    sid, _ = configured(client)
    page = client.get("/storage").text
    assert "call" in page and "2.0 KB" in page and f"/sessions/{sid}/delete-audio" in page


def test_failed_session_audio_can_be_deleted_but_retry_is_then_hidden(client):
    sid, folder = configured(client, status="failed")
    assert "Delete audio" in client.get(f"/sessions/{sid}").text
    client.post(f"/sessions/{sid}/delete-audio", follow_redirects=False)
    assert not folder.exists()
    # the transcript exists, so a retry (analysis only) is still possible
    assert "/retry" in client.get(f"/sessions/{sid}").text


def test_processing_session_audio_is_kept(client):
    sid, folder = configured(client, status="transcribing")
    client.post(f"/sessions/{sid}/delete-audio", follow_redirects=False)
    assert (folder / "me.wav").exists()


def test_retry_is_hidden_when_the_audio_is_gone_and_there_is_no_transcript(client):
    sid, _ = configured(client, status="failed")
    with DB(client.engine) as db:
        for u in db.exec(select(Utterance)).all():
            db.delete(u)
        db.commit()
    client.post(f"/sessions/{sid}/delete-audio", follow_redirects=False)
    page = client.get(f"/sessions/{sid}").text
    assert "/retry" not in page and "Cannot retry" in page
