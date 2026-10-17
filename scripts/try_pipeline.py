"""Прогон всего конвейера через веб-API на двух WAV-файлах.

Использование: LT_DATA_DIR=/tmp/lt-test uv run python scripts/try_pipeline.py me.wav partner.wav
"""

import re
import sys

from fastapi.testclient import TestClient

from langtrainer.web.app import app

me, partner = sys.argv[1], sys.argv[2]
with TestClient(app) as c:
    r = c.post(
        "/sessions",
        data={"title": "test"},
        files={"my_audio": open(me, "rb"), "partner_audio": open(partner, "rb")},
        follow_redirects=False,
    )
    page = c.get(r.headers["location"]).text
    print("status:", re.findall(r"Статус: <b>(\w+)</b>", page))
    print("errors:", re.findall(r"ошибок: (\d+)", page))
    print("shown:", re.findall(r"<del>([^<]*)</del> → <ins>([^<]*)</ins>", page))
