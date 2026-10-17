import urllib.error

import langtrainer


def test_browser_opens_once_the_server_answers(monkeypatch):
    attempts = []

    def urlopen(url, timeout):
        attempts.append(url)
        if len(attempts) < 3:
            raise urllib.error.URLError("not yet")

        class Response:
            def close(self):
                pass

        return Response()

    opened = []
    monkeypatch.setattr(langtrainer.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(langtrainer.time, "sleep", lambda s: None)
    assert langtrainer.open_when_ready("http://x/", opener=opened.append)
    assert opened == ["http://x/"] and len(attempts) == 3


def test_gives_up_when_the_server_never_starts(monkeypatch):
    monkeypatch.setattr(langtrainer.urllib.request, "urlopen", lambda *a, **k: (_ for _ in ()).throw(OSError()))
    monkeypatch.setattr(langtrainer.time, "sleep", lambda s: None)
    opened = []
    assert not langtrainer.open_when_ready("http://x/", timeout=0.01, opener=opened.append)
    assert opened == []
