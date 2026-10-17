from datetime import datetime, timedelta

from langtrainer.srs import AGAIN, EASY, GOOD, HARD, State, schedule

NOW = datetime(2026, 1, 1, 12, 0)
NEW = State(interval_days=0.0, ease=2.5, reps=0, lapses=0, due=NOW)


def test_good_progression():
    s1 = schedule(NEW, GOOD, NOW)
    assert (s1.interval_days, s1.reps) == (1.0, 1)
    s2 = schedule(s1, GOOD, NOW)
    assert s2.interval_days == 3.0
    s3 = schedule(s2, GOOD, NOW)
    assert s3.interval_days == 3.0 * 2.5
    assert s3.due == NOW + timedelta(days=7.5)


def test_again_resets_and_counts_lapse():
    s = schedule(schedule(NEW, GOOD, NOW), AGAIN, NOW)
    assert s.reps == 0 and s.lapses == 1
    assert s.due == NOW + timedelta(minutes=10)
    assert s.ease == 2.3


def test_ease_never_below_minimum():
    s = NEW
    for _ in range(20):
        s = schedule(s, AGAIN, NOW)
    assert s.ease == 1.3


def test_hard_and_easy_move_ease():
    assert schedule(NEW, HARD, NOW).ease < 2.5
    assert schedule(NEW, EASY, NOW).ease > 2.5
    assert schedule(NEW, EASY, NOW).interval_days > schedule(NEW, GOOD, NOW).interval_days
