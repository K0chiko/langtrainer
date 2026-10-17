# Language Trainer

A local app that listens to your conversations with a native speaker, finds your mistakes, and turns them into flashcards and personal advice.

Everything runs on your own computer. Audio is transcribed locally and never leaves your machine. Only the transcript text goes to a language model, and **you choose which one**:

- your **Claude subscription** through the Claude Code CLI (default, no API key);
- a **local model** such as Ollama or LM Studio, so nothing leaves your computer at all: see the [local models guide](docs/LOCAL_MODELS.md);
- a **paid API**: OpenAI, OpenRouter or any OpenAI-compatible service, or the Anthropic API.

The app is built to work in both directions: the learner's native and target languages are settings, not constants. Right now the default profile is Russian speaker learning English.

## How it works

```
Record (2 tracks) -> Whisper (local) -> Utterances -> Language model -> Mistakes -> Flashcards (SM-2) -> Advice
 mic | system audio   one track at a time   in DB      in DB      in DB
```

- **Two tracks instead of speaker detection.** The microphone is you, the system audio is the person on the call. Each track is transcribed separately, so there is no guessing who is speaking.
- **Transcription:** `faster-whisper` (CPU, or an NVIDIA GPU). On Apple Silicon you can switch to `mlx-whisper`, see [Configuration](#configuration).
- **Mistake analysis:** a language model of your choice (see [Choosing a language model](#choosing-a-language-model)). Utterances are sent in batches together with the neighbouring lines for context. Lines where speech recognition was unsure are flagged so recognition errors are not counted as your mistakes.
- **Flashcards and review:** each mistake becomes a card. Reviews are scheduled with a simplified SM-2 algorithm. A card you rate *Easy* three times in a row is marked **learned** and stops coming back; its history stays in your statistics, and you can return it to review from the Progress page.
- **Progress:** mistakes are grouped by rule to show your weak spots, and the model can write short advice for the most frequent ones.

The web interface has pages for sessions, all mistakes, card review and progress. Switch its language between English and Russian with the link in the top right corner. The explanations the model writes are in the learner's native language and do not depend on this switch.

## Requirements

| | macOS | Windows | Linux |
|---|---|---|---|
| Web app, transcription, cards, advice | yes | yes | yes |
| Built-in call recording | yes (macOS 15+) | yes (untested, see below) | not yet, upload files instead |

- Python 3.12 and [uv](https://docs.astral.sh/uv/).
- A language model for analysis, one of: [Claude Code](https://claude.com/claude-code) installed and signed in (`claude` then `/login`), a local model server, or an API key. See [Choosing a language model](#choosing-a-language-model).
- Disk space: about 1.3 GB for Python dependencies plus the Whisper model (a few hundred MB, downloaded on first use).
- macOS recording: Xcode Command Line Tools (`xcode-select --install`), used once to compile the recorder.

## Install and run

```bash
git clone <repository-url>
cd <repository-folder>
uv sync
uv run langtrainer
```

The page opens in your browser automatically (set `LT_OPEN_BROWSER=false` to turn that off). If it does not, open http://127.0.0.1:8000 yourself.

On the very first launch the app asks **where to keep its data** (the database and the recordings). Recordings are large, so choose a folder you can find and clean up yourself. A suggested folder (`Documents/LangTrainer`) is filled in; use *Browse…* or type any path, for example a folder on a NAS or an external drive. The choice is remembered, so you are not asked again.

### macOS: start it like a normal app

```bash
scripts/make_mac_app.sh
```

This builds `Language Trainer.app` in `~/Applications` (pass another folder as an argument to change that). Double-click it: it starts the server in the background and opens the page in your browser. Quit it from the Dock (right click, Quit) to stop the server; clicking its Dock icon again reopens the page. Server output goes to `data/server.log` inside the project folder. The app icon is `launcher/macos/icon.svg` (exported to `icon.icns`, and copied to `src/langtrainer/web/static/favicon.svg` for the browser tab); if the icon looks stale in Finder, run `killall Dock Finder`.

The first time you record a call, macOS asks for permission for the app. In System Settings, Privacy & Security, allow it under **Microphone** and **Screen & System Audio Recording** (the app is listed there as `applet`). Run the script again after moving the project folder, because the path is built into the app.

### Windows: start it with a double-click

Download or clone the project, then double-click `LangTrainer.bat` in the project folder. On the first run it installs [uv](https://docs.astral.sh/uv/) if it is missing, downloads Python and all dependencies (about 1.3 GB, this takes a while), starts the server and opens the page in your browser. Later runs start in a few seconds. Close the console window (or press Ctrl+C) to stop the server; server output also goes to `data\server.log`. If the app is already running, the batch file only opens the page.

To get a desktop icon, run `LangTrainer.bat --shortcut` once. Language model access works the same as on macOS: for Claude Code, install it and sign in once; the batch file adds `%USERPROFILE%\.local\bin` to `PATH`. Windows may ask for microphone access the first time you record (Settings, Privacy & security, Microphone, allow desktop apps).

Optional Apple Silicon speed-up: `uv sync --extra mlx`, then set `LT_TRANSCRIBER=mlx` (needs `ffmpeg` in PATH).

## Choosing a language model

Set `LT_LLM_PROVIDER` (in the environment or in a `.env` file). The same model is used for mistake analysis and for advice.

| Provider | Setup | Notes |
|---|---|---|
| `claude-cli` (default) | Install Claude Code and sign in. Nothing else. | Uses your subscription and its usage limits. No API key. |
| `openai` with a local server | `LT_LLM_BASE_URL=http://localhost:11434/v1` (Ollama), `LT_LLM_MODEL=<name>` | Free and fully private. Quality depends on the model. [Step-by-step guide](docs/LOCAL_MODELS.md). |
| `openai` with a hosted service | `LT_LLM_API_KEY`, `LT_LLM_MODEL`, and `LT_LLM_BASE_URL` for anything other than OpenAI (e.g. `https://openrouter.ai/api/v1`) | Works with any OpenAI-compatible API. |
| `anthropic` | `LT_LLM_API_KEY`, `LT_LLM_MODEL` | Anthropic API, billed per use. |

Example `.env` for a local model:

```
LT_LLM_PROVIDER=openai
LT_LLM_BASE_URL=http://localhost:11434/v1
LT_LLM_MODEL=qwen2.5:7b
LT_ANALYZE_BATCH_SIZE=15
```

Hosted APIs and the Claude subscription are far more accurate than small local models at spotting real mistakes without inventing fake ones. Dismissed false alarms never become cards.

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
| `LT_DATA_DIR` | not set | Folder for the database and audio. If not set, the app asks on first launch. See [Data folder](#data-folder). |
| `LT_OPEN_BROWSER` | `true` | Open the page in the browser when `langtrainer` starts. |
| `LT_DATABASE_URL` | empty | SQLAlchemy URL. Empty means SQLite in the data folder. |
| `LT_TRANSCRIBER` | `auto` | `auto` (= faster-whisper), `faster-whisper` or `mlx` (Mac only, needs ffmpeg). |
| `LT_WHISPER_MODEL` | `small` | Whisper model. Use `small.en` or `medium.en` for English-only, more accurate. |
| `LT_LLM_PROVIDER` | `claude-cli` | `claude-cli`, `openai` (any OpenAI-compatible server) or `anthropic`. |
| `LT_LLM_MODEL` | empty | Model name. Optional for `claude-cli` (empty = CLI default), required otherwise. |
| `LT_LLM_BASE_URL` | empty | Server URL for `openai`, e.g. `http://localhost:11434/v1`. Empty = OpenAI. |
| `LT_LLM_API_KEY` | empty | API key for hosted services. Local servers usually need none. |
| `LT_LLM_TIMEOUT` | `600` | Seconds per request. Raise it for slow local models. |
| `LT_ANALYZE_BATCH_SIZE` | `60` | Utterances per analysis request. Use 10-20 for small local models. |

Do not put the SQLite file on a network share (SMB/NFS): file locking over the network is unreliable. Use a local file with backups, or PostgreSQL via `LT_DATABASE_URL`.

## Data folder

The app stores everything it creates in one folder: `langtrainer.db` (conversations, mistakes, cards) and `audio/` (one subfolder per conversation).

Where the folder comes from, strongest first:
1. the `LT_DATA_DIR` environment variable;
2. `LT_DATA_DIR` in a `.env` file;
3. the folder chosen in the app on first launch. It is remembered in a tiny `config.json` in your user profile (macOS `~/Library/Application Support/LangTrainer`, Windows `%APPDATA%\LangTrainer`, Linux `~/.config/langtrainer`). That file holds only the folder path.

The **Storage** page shows the folder, how much space the database and audio take, and the audio size of each conversation. From there you can open the folder in Finder/Explorer and delete the audio of a finished or failed conversation (not while it is being processed). Deleting audio keeps its text, mistakes and cards; for a failed conversation it means you can no longer retry the transcription. To free more space, delete a whole conversation from its page. Changing the folder after the first choice is not supported in the app yet: set `LT_DATA_DIR`, or remove `config.json` to be asked again, and move the files yourself.

## Project layout

```
src/langtrainer/
  web/            FastAPI app and HTML templates
  llm.py          language model providers (Claude CLI, OpenAI-compatible, Anthropic)
  analyzers/      Analyzer interface and the prompt-based analyzer
  i18n.py         interface strings (English, Russian)
  transcribers/   Transcriber interface, faster-whisper and mlx-whisper
  pipeline.py     transcribe -> analyze steps, each restartable
  storage.py      data folder choice, disk usage
  recording.py    recorder facade and the macOS backend
  recording_windows.py  Windows backend (WASAPI loopback)
  cards.py, srs.py, stats.py, advisor.py
LangTrainer.bat   Windows launcher (installs uv, syncs dependencies, starts the server)
recorder/macos/   Swift source of the macOS recorder
scripts/          manual check scripts (macOS only)
tests/
docs/             guides (local models)
ARCHITECTURE.md   design notes and plan
```

## Development

```bash
uv sync
uv run pytest
```

## Known limitations

- The interface has two languages (English, Russian). Adding another means adding a block to `src/langtrainer/i18n.py`.
- One learner profile per database (the first one is used everywhere). A mirror profile for the partner is planned.
- Recording is not implemented for Linux.
- The data folder cannot be changed from inside the app after the first launch (see [Data folder](#data-folder)).
- Speech recognition of accented speech is imperfect, so some reported mistakes are noise. Dismiss them in the interface and they will not become cards.
- With the `claude-cli` provider, your subscription's usage limits apply.
- OpenAI-compatible and Anthropic providers are tested against a simulated server only, not yet against every real runtime.

## Keeping this file current

Any significant change to the app (features, setup, configuration, supported platforms) must update this README in the same commit.
