from datetime import timedelta

from sqlmodel import select

from langtrainer import pipeline, progress
from langtrainer.analyzers import Finding
from langtrainer.models import Error, Participant, Session, SessionProgress, Utterance, _utcnow
from langtrainer.transcribers import Segment
from tests.test_cards import make_db

T0 = _utcnow()


def test_eta_needs_enough_data():
    assert progress.eta_seconds(0, 100, T0, T0 + timedelta(minutes=5)) is None  # ничего не сделано
    assert progress.eta_seconds(1, 100, T0, T0 + timedelta(minutes=5)) is None  # меньше 3%
    assert progress.eta_seconds(50, 100, T0, T0 + timedelta(seconds=5)) is None  # слишком рано
    assert progress.eta_seconds(5, 0, T0, T0 + timedelta(minutes=5)) is None  # объём неизвестен


def test_eta_extrapolates_speed():
    # за 10 минут сделана четверть, значит осталось 30
    assert progress.eta_seconds(25, 100, T0, T0 + timedelta(minutes=10)) == 30 * 60
    assert progress.eta_seconds(100, 100, T0, T0 + timedelta(minutes=10)) == 0


def test_job_view():
    assert progress.job_view(None, "done") is None
    assert progress.job_view(None, "uploaded").percent is None
    row = SessionProgress(session_id=1, phase="transcribing", done=30, total=120, phase_started_at=T0)
    view = progress.job_view(row, "transcribing", now=T0 + timedelta(minutes=2))
    assert (view.phase, view.percent, view.eta) == ("transcribing", 25, 360)
    row.total = 0
    assert progress.job_view(row, "transcribing").percent is None


def test_mark_interrupted_only_touches_unfinished():
    db, learner, conv, part = make_db()
    done = Session(learner_id=learner.id, status="done")
    busy = Session(learner_id=learner.id, status="transcribing")
    db.add_all([done, busy])
    db.commit()
    conv.status = "analyzing"
    db.add(conv)
    db.commit()
    assert progress.mark_interrupted(db) == 2
    db.refresh(done), db.refresh(busy), db.refresh(conv)
    assert done.status == "done"
    assert (busy.status, busy.status_detail) == ("failed", progress.INTERRUPTED)
    assert conv.status == "failed"


class FakeTranscriber:
    def transcribe(self, audio_path, lang, on_progress=None):
        for end in (10.0, 20.0, 30.0):
            on_progress(end, 30.0)
        return [Segment(0, 30, f"text from {audio_path}", 0.9)]


def test_transcribe_session_reports_progress_across_tracks(monkeypatch):
    db, learner, conv, part = make_db()
    db.add(Participant(session_id=conv.id, role="partner", lang="en", audio_path="partner.wav"))
    db.commit()
    seen = []
    real = pipeline.set_progress

    def spy(db_, session_id, phase, done, total, **kw):
        seen.append((phase, done, total))
        real(db_, session_id, phase, done, total, **kw)

    monkeypatch.setattr(pipeline, "get_transcriber", lambda: FakeTranscriber())
    monkeypatch.setattr(pipeline, "audio_duration", lambda path: 30.0)
    monkeypatch.setattr(pipeline, "set_progress", spy)
    monkeypatch.setattr(pipeline.time, "monotonic", iter(range(0, 1000, 5)).__next__)  # без троттлинга
    pipeline.transcribe_session(db, conv.id)

    assert seen[0] == ("transcribing", 0, 60.0)  # общий объём — обе дорожки
    assert seen[-1] == ("transcribing", 60.0, 60.0)
    assert max(d for _, d, _ in seen[:-1]) > 30.0  # вторая дорожка продолжила отсчёт с 30
    assert len(db.exec(select(Utterance)).all()) == 2


def test_unknown_duration_gives_indeterminate_progress(monkeypatch):
    db, learner, conv, part = make_db()
    monkeypatch.setattr(pipeline, "get_transcriber", lambda: FakeTranscriber())
    monkeypatch.setattr(pipeline, "audio_duration", lambda path: None)
    pipeline.transcribe_session(db, conv.id)
    row = db.get(SessionProgress, conv.id)
    assert row.total == 0
    assert progress.job_view(row, "transcribing").percent is None


class FakeAnalyzer:
    def analyze(self, profile, lines, on_progress=None):
        on_progress(0, 2)
        on_progress(1, 2)
        on_progress(2, 2)
        learner_line = next(ln for ln in lines if ln.role == "learner")
        return [Finding(learner_line.utterance_id, "tense", "I go", "I went", "why", 2, "tense.past_simple")]


def test_analyze_session_reports_batches(monkeypatch):
    db, learner, conv, part = make_db()
    db.add(Utterance(session_id=conv.id, participant_id=part.id, start=0, end=1, text="I go home"))
    db.commit()
    monkeypatch.setattr(pipeline, "get_analyzer", lambda: FakeAnalyzer())
    pipeline.analyze_session(db, conv.id)
    row = db.get(SessionProgress, conv.id)
    assert (row.phase, row.done, row.total) == ("analyzing", 2, 2)
    assert len(db.exec(select(Error)).all()) == 1
