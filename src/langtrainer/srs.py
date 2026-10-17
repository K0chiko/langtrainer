"""Расписание повторов: упрощённый SM-2. Чистая функция, без БД, чтобы её было легко тестировать."""

from dataclasses import dataclass
from datetime import datetime, timedelta

AGAIN, HARD, GOOD, EASY = 1, 2, 3, 4
MIN_EASE = 1.3
AGAIN_DELAY = timedelta(minutes=10)


@dataclass
class State:
    interval_days: float
    ease: float
    reps: int
    lapses: int
    due: datetime


def schedule(state: State, rating: int, now: datetime) -> State:
    if rating not in (AGAIN, HARD, GOOD, EASY):
        raise ValueError(f"bad rating: {rating}")
    ease, interval, reps, lapses = state.ease, state.interval_days, state.reps, state.lapses

    if rating == AGAIN:
        return State(0.0, max(MIN_EASE, ease - 0.2), 0, lapses + 1, now + AGAIN_DELAY)

    if rating == HARD:
        interval = max(1.0, interval * 1.2)
        ease = max(MIN_EASE, ease - 0.15)
    elif rating == GOOD:
        interval = 1.0 if reps == 0 else 3.0 if reps == 1 else interval * ease
    else:  # EASY
        interval = 4.0 if reps == 0 else interval * ease * 1.3 if reps > 1 else 6.0
        ease += 0.15
    return State(interval, ease, reps + 1, lapses, now + timedelta(days=interval))
