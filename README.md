# Language Trainer

A local app that listens to your conversations with a native speaker, finds your mistakes, and turns them into flashcards and personal advice.

Everything runs on your own computer. Audio is transcribed locally and never leaves your machine; only the transcript text is sent to Claude for analysis.

The app is built to work in both directions: the learner's native and target languages are settings, not constants. Right now the default profile is Russian speaker learning English.

## How it works

```
Record (2 tracks) -> Whisper (local) -> Utterances -> Claude -> Mistakes -> Flashcards (SM-2) -> Advice
 mic | system audio   one track at a time   in DB      in DB      in DB
```

- **Two tracks instead of speaker detection.** The microphone is you, the system audio is the person on the call. Each track is transcribed separately, so there is no guessing who is speaking.
- **Transcription:** `faster-whisper` (CPU, or an NVIDIA GPU). On Apple Silicon you can switch to `mlx-whisper`, see [Configuration](#configuration).
- **Mistake analysis:** the app runs the Claude Code CLI (`claude -p`) under your own Claude subscription. No API key is needed. Utterances are sent in batches together with the neighbouring lines for context. Lines where speech recognition was unsure are flagged so recognition errors are not counted as your mistakes.
- **Flashcards and review:** each mistake becomes a card. Reviews are scheduled with a simplified SM-2 algorithm.
- **Progress:** mistakes are grouped by rule to show your weak spots, and Claude can write short advice for the most frequent ones.

The web interface (currently in Russian) has pages for sessions, all mistakes, card review and progress.

## Requirements

| | macOS | Windows | Linux |
|---|---|---|---|
| Web app, transcription, cards, advice | yes | yes | yes |
| Built-in call recording | yes (macOS 15+) | yes (untested, see below) | not yet, upload files instead |

- Python 3.12 and [uv](https://docs.astral.sh/uv/).
- [Claude Code](https://claude.com/claude-code) installed and signed in (`claude` then `/login`). Analysis and advice use your subscription and its usage limits.
- Disk space: about 1.3 GB for Python dependencies plus the Whisper model (a few hundred MB, downloaded on first use).
- macOS recording: Xcode Command Line Tools (`xcode-select --install`), used once to compile the recorder.

## Install and run

```bash
git clone <repository-url>
cd <repository-folder>
uv sync
uv run langtrainer
```

Then open http://127.0.0.1:8000 in your browser.

Optional Apple Silicon speed-up: `uv sync --extra mlx`, then set `LT_TRANSCRIBER=mlx` (needs `ffmpeg` in PATH).

## Recording a call

On the home page press the record button ("Начать запись") before the call and stop it ("Остановить и разобрать") after it. The two tracks are saved, transcribed and analysed automatically. You can follow the status on the session page.

Always get the other person's consent before recording.

**macOS.** The first recording asks for *Screen & System Audio Recording* and *Microphone* permission (System Settings > Privacy & Security). The recorder is a small Swift program in `recorder/macos/`, built automatically on first use.

**Windows.** The microphone is the default input device and the system audio is captured through WASAPI loopback from the default output device, so no extra drivers are needed. Use the speakers or headphones that are set as the default output while you call. If nothing plays for a while, silence is inserted so both tracks stay aligned. This recorder was written without access to a Windows machine and has not been tested on real hardware yet; please report problems.

**Without the recorder.** Use the upload form on the home page: your audio file is required, the partner's is optional. Any format that ffmpeg/PyAV can read works. Separate tracks give much better results than one mixed file.

## Configuration

Settings are read from environment variables with the `LT_` prefix or from a `.env` file in the folder where you start the app.

| Variable | Default | Meaning |
|---|---|---|
| `LT_DATA_DIR` | `data` | Folder for the database and audio. Can point to a network drive. |
| `LT_DATABASE_URL` | empty | SQLAlchemy URL. Empty means SQLite in the data folder. |
| `LT_TRANSCRIBER` | `auto` | `auto` (= faster-whisper), `faster-whisper` or `mlx` (Mac only, needs ffmpeg). |
| `LT_WHISPER_MODEL` | `small` | Whisper model. Use `small.en` or `medium.en` for English-only, more accurate. |
| `LT_ANALYZER` | `claude-cli` | Mistake analyzer. Only `claude-cli` exists so far. |
| `LT_CLAUDE_MODEL` | empty | Model passed to the Claude CLI. Empty means the CLI default. |
| `LT_ANALYZE_BATCH_SIZE` | `60` | Utterances per analysis request. |

Do not put the SQLite file on a network share (SMB/NFS): file locking over the network is unreliable. Use a local file with backups, or PostgreSQL via `LT_DATABASE_URL`.

## Project layout

```
src/langtrainer/
  web/            FastAPI app and HTML templates
  analyzers/      Analyzer interface and the Claude CLI implementation
  transcribers/   Transcriber interface, faster-whisper and mlx-whisper
  pipeline.py     transcribe -> analyze steps, each restartable
  recording.py    recorder facade and the macOS backend
  recording_windows.py  Windows backend (WASAPI loopback)
  cards.py, srs.py, stats.py, advisor.py
recorder/macos/   Swift source of the macOS recorder
scripts/          manual check scripts (macOS only)
tests/
ARCHITECTURE.md   design notes and plan
```

## Development

```bash
uv sync
uv run pytest
```

## Known limitations

- The web interface text is Russian only.
- One learner profile per database (the first one is used everywhere). A mirror profile for the partner is planned.
- Recording is not implemented for Linux.
- Speech recognition of accented speech is imperfect, so some reported mistakes are noise. Dismiss them in the interface and they will not become cards.
- Claude Code usage limits of your subscription apply.

## Keeping this file current

Any significant change to the app (features, setup, configuration, supported platforms) must update this README in the same commit.
