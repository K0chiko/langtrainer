from sqlmodel import Session, SQLModel, create_engine, select

from langtrainer import cards
from langtrainer.models import Card, Error, Learner, Participant, Review, Utterance
from langtrainer.models import Session as Conv


def make_db():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    db = Session(engine)
    learner = Learner(name="t")
    db.add(learner)
    db.commit()
    conv = Conv(learner_id=learner.id)
    db.add(conv)
    db.commit()
    part = Participant(session_id=conv.id, role="learner", lang="en", audio_path="x")
    db.add(part)
    db.commit()
    return db, learner, conv, part


def add_error(db, learner, conv, part, text, original, corrected):
    u = Utterance(session_id=conv.id, participant_id=part.id, start=0, end=1, text=text)
    db.add(u)
    db.commit()
    e = Error(
        utterance_id=u.id, learner_id=learner.id, category="tense", original=original,
        corrected=corrected, explanation="why",
    )
    db.add(e)
    db.commit()
    return e


def test_generate_is_idempotent_and_builds_fixed_sentence():
    db, learner, conv, part = make_db()
    add_error(db, learner, conv, part, "Yesterday I go home.", "I go", "I went")
    assert cards.generate_cards(db, learner.id) == 1
    assert cards.generate_cards(db, learner.id) == 0
    card = db.exec(select(Card)).one()
    assert card.front == "Yesterday I go home."
    assert card.back == "Yesterday I went home."


def test_same_mistake_is_not_duplicated():
    db, learner, conv, part = make_db()
    add_error(db, learner, conv, part, "I go home.", "I go", "I went")
    add_error(db, learner, conv, part, "Then I go out.", "I go", "I went")
    assert cards.generate_cards(db, learner.id) == 1


def test_dismissed_error_gets_no_card_and_suspends_existing():
    db, learner, conv, part = make_db()
    e = add_error(db, learner, conv, part, "I go home.", "I go", "I went")
    cards.generate_cards(db, learner.id)
    assert cards.due_count(db, learner.id) == 1
    cards.set_suspended(db, e.id, True)
    assert cards.due_count(db, learner.id) == 0


def test_review_reschedules_and_logs():
    db, learner, conv, part = make_db()
    add_error(db, learner, conv, part, "I go home.", "I go", "I went")
    cards.generate_cards(db, learner.id)
    card = cards.next_due(db, learner.id)
    cards.review(db, card.id, 3)
    assert cards.due_count(db, learner.id) == 0  # следующий повтор завтра
    assert db.exec(select(Review)).one().rating == 3
    card = db.get(Card, card.id)
    assert card.reps == 1 and card.interval_days == 1.0


def test_unreviewed_cards_are_dropped_reviewed_are_kept():
    db, learner, conv, part = make_db()
    e1 = add_error(db, learner, conv, part, "I go home.", "I go", "I went")
    e2 = add_error(db, learner, conv, part, "Two apple.", "two apple", "two apples")
    cards.generate_cards(db, learner.id)
    c1 = db.exec(select(Card).where(Card.error_id == e1.id)).one()
    cards.review(db, c1.id, 3)
    kept = cards.delete_unreviewed_cards(db, [e1.id, e2.id])
    assert kept == {e1.id}
    assert db.exec(select(Card)).one().error_id == e1.id


def test_rating_options_show_growing_waits():
    db, learner, conv, part = make_db()
    add_error(db, learner, conv, part, "I go home.", "I go", "I went")
    cards.generate_cards(db, learner.id)
    options = cards.rating_options(cards.next_due(db, learner.id))
    assert [o[0] for o in options] == [1, 2, 3, 4]
    assert options[0][2] == ("minutes", 10)
    assert options[2][2] == ("days", 1)


def _card(db, learner, conv, part):
    add_error(db, learner, conv, part, "I go to school.", "go", "went")
    cards.generate_cards(db, learner.id)
    return db.exec(select(Card)).first()


def test_three_easy_in_a_row_marks_the_card_learned(monkeypatch):
    db, learner, conv, part = make_db()
    card = _card(db, learner, conv, part)
    assert cards.review(db, card.id, 4) is False
    assert cards.review(db, card.id, 4) is False
    assert cards.review(db, card.id, 4) is True
    db.refresh(card)
    assert card.learned and card.easy_streak == 3
    assert db.exec(select(Review)).all().__len__() == 3  # history is kept
    card.due = card.due.replace(year=2000)
    db.add(card)
    db.commit()
    assert cards.next_due(db, learner.id) is None and cards.due_count(db, learner.id) == 0
    assert cards.generate_cards(db, learner.id) == 0  # not recreated


def test_a_non_easy_answer_resets_the_streak():
    db, learner, conv, part = make_db()
    card = _card(db, learner, conv, part)
    for rating in (4, 4, 3, 4, 4):
        assert cards.review(db, card.id, rating) is False
    db.refresh(card)
    assert not card.learned and card.easy_streak == 2


def test_unlearn_returns_the_card_with_a_fresh_streak():
    db, learner, conv, part = make_db()
    card = _card(db, learner, conv, part)
    for _ in range(3):
        cards.review(db, card.id, 4)
    assert [c.id for c in cards.learned_cards(db, learner.id)] == [card.id]
    cards.unlearn(db, card.id)
    db.refresh(card)
    assert not card.learned and card.easy_streak == 0
    assert cards.next_due(db, learner.id).id == card.id
    assert cards.review(db, card.id, 4) is False  # needs three new Easy answers
