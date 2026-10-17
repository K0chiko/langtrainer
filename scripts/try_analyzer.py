"""Быстрая проверка разбора ошибок на трёх фразах с заведомыми ошибками."""

from langtrainer.analyzers import LearnerProfile, Line, get_analyzer

lines = [
    Line(1, "partner", "So what did you do last weekend?", 0.95),
    Line(2, "learner", "Last weekend I go to the mountains with my friend.", 0.9),
    Line(3, "partner", "Nice! Was the weather good?", 0.95),
    Line(4, "learner", "Yes, it was very good weather and we have a lot of fun.", 0.9),
    Line(5, "learner", "I am working in this company since two years.", 0.9),
    Line(6, "learner", "Yeah, gonna grab some coffee, you know.", 0.9),
]
for f in get_analyzer().analyze(LearnerProfile("ru", "en"), lines):
    print(f)
