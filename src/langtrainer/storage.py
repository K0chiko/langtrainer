"""Where the app keeps its data (database and audio), and how much space it takes.

The folder is chosen by the user on first launch. The choice is remembered in a tiny config.json in the
user's profile; nothing else lives there. Precedence, strongest first:
  1. the LT_DATA_DIR environment variable, 2. LT_DATA_DIR in a .env file, 3. the folder chosen in the app.
"""

import json
import os
import platform
import subprocess
import sys
from dataclasses import dataclass
from importlib.util import find_spec
from pathlib import Path

from .config import settings

APP_NAME = "LangTrainer"
DB_FILE = "langtrainer.db"
SOURCE_ENV, SOURCE_APP = "environment", "app"

_source = ""


class StorageError(ValueError):
    """The chosen folder cannot be used. `code` is an interface string key suffix (setup.err.<code>)."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def config_file() -> Path:
    override = os.environ.get("LT_CONFIG_DIR")
    if override:
        return Path(override) / "config.json"
    system = platform.system()
    if system == "Windows":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming") / APP_NAME
    elif system == "Darwin":
        base = Path.home() / "Library" / "Application Support" / APP_NAME
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / APP_NAME.lower()
    return base / "config.json"


def load_saved_data_dir() -> Path | None:
    try:
        value = json.loads(config_file().read_text(encoding="utf-8")).get("data_dir")
    except (OSError, ValueError, AttributeError):
        return None
    return Path(value) if value else None


def save_data_dir(path: Path) -> None:
    file = config_file()
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(json.dumps({"data_dir": str(path)}, indent=2), encoding="utf-8")


def needs_setup() -> bool:
    return settings.data_dir is None


def apply_saved() -> None:
    """Fill settings.data_dir from the remembered choice unless the environment or .env already set it."""
    global _source
    if settings.data_dir is not None:
        _source = _source or SOURCE_ENV
        return
    saved = load_saved_data_dir()
    if saved is not None:
        settings.data_dir, _source = saved, SOURCE_APP


def source() -> str:
    """Where the active folder came from: SOURCE_APP (chosen in the app) or SOURCE_ENV."""
    return _source or SOURCE_ENV


def validate_folder(raw: str) -> Path:
    """Create the folder if needed and check that we can write into it."""
    raw = raw.strip().strip('"')
    if not raw:
        raise StorageError("empty")
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    if path.exists() and not path.is_dir():
        raise StorageError("not_dir")
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".write-test"
        probe.write_text("ok")
        probe.unlink()
    except OSError as exc:
        raise StorageError("not_writable") from exc
    return path.resolve()


def choose_data_dir(raw: str) -> Path:
    path = validate_folder(raw)
    save_data_dir(path)
    global _source
    settings.data_dir, _source = path, SOURCE_APP
    return path


def suggested_folders() -> list[tuple[str, Path]]:
    """(kind, path) options for the setup screen: a data folder found next to where the app was started, then a default."""
    options: list[tuple[str, Path]] = []
    found = Path.cwd() / "data"
    if (found / DB_FILE).exists():
        options.append(("existing", found))
    documents = Path.home() / "Documents"
    options.append(("default", (documents if documents.is_dir() else Path.home()) / APP_NAME))
    return options


@dataclass
class Usage:
    database: int
    audio: int
    per_session: dict[int, int]


def _tree_size(path: Path) -> int:
    total = 0
    for item in path.rglob("*"):
        try:
            if item.is_file():
                total += item.stat().st_size
        except OSError:
            continue
    return total


def session_audio_bytes(audio_dir: Path, session_id: int) -> int:
    folder = audio_dir / str(session_id)
    return _tree_size(folder) if folder.is_dir() else 0


def usage(data_dir: Path) -> Usage:
    db_file = data_dir / DB_FILE
    audio_dir = data_dir / "audio"
    per_session: dict[int, int] = {}
    if audio_dir.is_dir():
        for folder in audio_dir.iterdir():
            if folder.is_dir() and folder.name.isdigit():
                per_session[int(folder.name)] = _tree_size(folder)
    return Usage(
        database=db_file.stat().st_size if db_file.exists() else 0,
        audio=_tree_size(audio_dir) if audio_dir.is_dir() else 0,
        per_session=per_session,
    )


def format_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{size} B"


def open_folder(path: Path) -> None:
    system = platform.system()
    if system == "Windows":
        os.startfile(path)  # noqa: S606 - the path is the configured data folder, never user input
    elif system == "Darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


_BROWSE_SCRIPT = """
import sys, tkinter
from tkinter import filedialog
root = tkinter.Tk()
root.withdraw()
root.attributes("-topmost", True)
print(filedialog.askdirectory(initialdir=sys.argv[1], mustexist=False) or "")
"""


def browse_available() -> bool:
    return find_spec("tkinter") is not None


def browse_folder(initial: str = "") -> str:
    """Native folder picker in a separate process (Tk must own the main thread). Empty string = cancelled."""
    start = initial if initial and Path(initial).expanduser().is_dir() else str(Path.home())
    try:
        result = subprocess.run(
            [sys.executable, "-c", _BROWSE_SCRIPT, start], capture_output=True, text=True, timeout=600
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""
