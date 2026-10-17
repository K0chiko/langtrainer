"""Вызов Claude Code CLI (`claude -p`) под подпиской пользователя, без API-ключа. Общий для анализатора и советов."""

import json
import subprocess
import tempfile

from .config import settings


def ask_json(prompt: str, schema: dict, timeout: int = 600) -> dict:
    """Отправляет prompt и возвращает JSON-ответ, соответствующий schema."""
    cmd = [
        "claude",
        "-p",
        "--output-format",
        "json",
        "--json-schema",
        json.dumps(schema),
        "--tools",
        "",
        "--no-session-persistence",
        "--strict-mcp-config",
    ]
    if settings.llm_model:
        cmd += ["--model", settings.llm_model]
    # Отдельная пустая рабочая папка, чтобы CLI не подхватывал чужие CLAUDE.md и настройки проекта
    with tempfile.TemporaryDirectory() as cwd:
        proc = subprocess.run(cmd, input=prompt, capture_output=True, text=True, cwd=cwd, timeout=timeout)
    if proc.returncode != 0:
        try:
            detail = json.loads(proc.stdout).get("result", "")
        except ValueError:
            detail = proc.stderr.strip() or proc.stdout.strip()
        hint = " Run `claude` in a terminal and sign in with /login." if "authenticate" in detail else ""
        raise RuntimeError(f"claude CLI failed ({proc.returncode}): {detail}.{hint}")
    envelope = json.loads(proc.stdout)
    if envelope.get("is_error"):
        raise RuntimeError(f"claude CLI error: {envelope.get('result')}")
    data = envelope.get("structured_output")
    if data is None:
        text = envelope.get("result", "")
        data = json.loads(text[text.index("{") : text.rindex("}") + 1])
    return data
