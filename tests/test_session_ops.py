import pytest
from sqlmodel import select

from langtrainer import session_ops
from langtrainer.models import Card, Error, Participant, Review, Session, SessionProgress, Utterance
from tests.test_cards import add_error, make_db


def make_conversation(tmp_path):
    db, learner, conv, part = make_db()
    conv.status, conv.title = "done", "Old name"
    db.add(conv)
    db.commit()
    e = add_error(db, learner, conv, part, "I go home.", "I go", "I went")
    card = Card(learner_id=learner.id, error_id=e.id, front="a", back="b")
    db.add(card)
    db.add(SessionProgress(session_id=conv.id, phase="analyzing", done=1, total=1))
    db.commit()
    audio = tmp_path / str(conv.id)
    audio.mkdir()
    (audio / "me.wav").write_bytes(b"x")
    return db, learner, conv, card, audio


def test_rename_cleans_and_ignores_empty():
    db, learner, conv, part = make_db()
    assert session_ops.rename_session(db, conv.id, "  Talk   with   Anna \n") is True
    assert db.get(Session, conv.id).title == "Talk with Anna"
    assert session_ops.rename_session(db, conv.id, "   ") is False  # пустое название: остаётся прежнее
    assert session_ops.rename_session(db, conv.id, "Talk with Anna") is False
    assert db.get(Session, conv.id).title == "Talk with Anna"
    session_ops.rename_session(db, conv.id, "x" * 500)
    assert len(db.get(Session, conv.id).title) == session_ops.MAX_TITLE


def test_impact_counts_reviewed_cards(tmp_path):
    db, learner, conv, card, audio = make_conversation(tmp_path)
    impact = session_ops.deletion_impact(db, conv.id)
    assert (impact.utterances, impact.errors, impact.cards, impact.reviewed_cards) == (1, 1, 1, 0)
    card.reps = 2
    db.add(card)
    db.commit()
    assert session_ops.deletion_impact(db, conv.id).reviewed_cards == 1


def test_delete_removes_everything_including_audio(tmp_path):
    db, learner, conv, card, audio = make_conversation(tmp_path)
    db.add(Review(card_id=card.id, rating=3))
    keep_audio = tmp_path / "999"
    keep_audio.mkdir()
    db.commit()
    session_ops.delete_session(db, conv.id, tmp_path)
    for model in (Session, Participant, Utterance, Error, Card, Review, SessionProgress):
        assert db.exec(select(model)).all() == [], model.__name__
    assert not audio.exists()
    assert keep_audio.exists()  # чужие папки не трогаем


def test_delete_leaves_other_conversations_alone(tmp_path):
    db, learner, conv, card, audio = make_conversation(tmp_path)
    other = Session(learner_id=learner.id, status="done", title="Other")
    db.add(other)
    db.commit()
    other_part = Participant(session_id=other.id, role="learner", lang="en", audio_path="y")
    db.add(other_part)
    db.commit()
    other_err = add_error(db, learner, other, other_part, "Two apple.", "two apple", "two apples")
    other_card = Card(learner_id=learner.id, error_id=other_err.id, front="c", back="d")
    db.add(other_card)
    db.commit()
    session_ops.delete_session(db, conv.id, tmp_path)
    assert [s.id for s in db.exec(select(Session))] == [other.id]
    assert [c.id for c in db.exec(select(Card))] == [other_card.id]


@pytest.mark.parametrize("status", ["uploaded", "transcribing", "analyzing"])
def test_cannot_delete_while_processing(tmp_path, status):
    db, learner, conv, card, audio = make_conversation(tmp_path)
    conv.status = status
    db.add(conv)
    db.commit()
    with pytest.raises(session_ops.SessionBusy):
        session_ops.delete_session(db, conv.id, tmp_path)
    assert audio.exists() and db.get(Session, conv.id) is not None


def test_delete_missing_session_is_a_noop(tmp_path):
    db, *_ = make_db()
    session_ops.delete_session(db, 12345, tmp_path)
