import time
import urllib.request
import webbrowser

HOST, PORT = "127.0.0.1", 8000


def open_when_ready(url: str, timeout: float = 60, opener=webbrowser.open) -> bool:
    """Wait until the server answers, then open the page in the default browser."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            urllib.request.urlopen(url, timeout=2).close()
        except OSError:
            time.sleep(0.3)
            continue
        opener(url)
        return True
    return False


def main() -> None:
    import threading

    import uvicorn

    from .config import settings

    if settings.open_browser:
        threading.Thread(target=open_when_ready, args=(f"http://{HOST}:{PORT}/",), daemon=True).start()
    uvicorn.run("langtrainer.web.app:app", host=HOST, port=PORT)
