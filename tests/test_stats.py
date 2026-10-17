from datetime import timedelta

from langtrainer import stats
from langtrainer.models import Card, Error, Review, Utterance, _utcnow
from tests.test_cards import add_error, make_db


def test_weak_spots_group_and_order():
    db, learner, conv, part = make_db()
    for i in range(3):
        e = add_error(db, learner, conv, part, f"I go {i}.", "I go", "I went")
        e.rule_key = "tense.past_simple"
        db.add(e)
    e = add_error(db, learner, conv, part, "Two apple.", "two apple", "two apples")
    e.rule_key = "plural.missing_s"
    db.add(e)
    db.commit()
    spots = stats.weak_spots(db, learner.id)
    assert [(s.rule, s.count) for s in spots] == [("tense.past_simple", 3), ("plural.missing_s", 1)]
    assert len(spots[0].examples) == 3


def test_dismissed_errors_are_ignored():
    db, learner, conv, part = make_db()
    e = add_error(db, learner, conv, part, "I go.", "I go", "I went")
    e.dismissed = True
    db.add(e)
    db.commit()
    assert stats.weak_spots(db, learner.id) == []


def test_recent_window():
    db, learner, conv, part = make_db()
    e = add_error(db, learner, conv, part, "I go.", "I go", "I went")
    e.rule_key = "tense.past_simple"
    e.created_at = _utcnow() - timedelta(days=30)
    db.add(e)
    db.commit()
    assert stats.weak_spots(db, learner.id)[0].recent == 0


def test_session_series_errors_per_100_words():
    db, learner, conv, part = make_db()
    conv.status = "done"
    db.add(conv)
    add_error(db, learner, conv, part, "I go to the store now " * 5, "I go", "I went")  # 6 слов x 5 = 30 слов, 1 ошибка
    db.commit()
    point = stats.session_series(db, learner.id)[0]
    assert (point.words, point.errors, point.per100) == (30, 1, 3.3)


def test_review_stats_retention():
    db, learner, conv, part = make_db()
    e = add_error(db, learner, conv, part, "I go.", "I go", "I went")
    card = Card(learner_id=learner.id, error_id=e.id, front="a", back="b")
    db.add(card)
    db.commit()
    for rating in (1, 3, 4, 3):
        db.add(Review(card_id=card.id, rating=rating))
    db.commit()
    rs = stats.review_stats(db, learner.id)
    assert (rs.cards, rs.due, rs.reviews_7d, rs.retention_pct) == (1, 1, 4, 75)
