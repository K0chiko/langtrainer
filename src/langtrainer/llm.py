"""One entry point for every language-model backend the app can use.

Providers (LT_LLM_PROVIDER):
- claude-cli: the Claude Code CLI under the user's subscription, no API key (default)
- openai:     any OpenAI-compatible chat endpoint: OpenAI, OpenRouter, and local servers such as Ollama,
              LM Studio, llama.cpp and vLLM (set LT_LLM_BASE_URL)
- anthropic:  the Anthropic API with an API key
"""

import json
import urllib.error
import urllib.request

from .config import settings

OPENAI_DEFAULT_URL = "https://api.openai.com/v1"
ANTHROPIC_DEFAULT_URL = "https://api.anthropic.com"
ANTHROPIC_MAX_TOKENS = 8192


class LlmError(RuntimeError):
    pass


def ask_json(prompt: str, schema: dict, timeout: int | None = None) -> dict:
    """Sends the prompt and returns a JSON object that has every top-level key the schema requires."""
    timeout = timeout or settings.llm_timeout
    provider = settings.llm_provider
    if provider == "claude-cli":
        from .claude_cli import ask_json as ask_cli

        data = ask_cli(prompt, schema, timeout)
    elif provider == "openai":
        data = _ask_openai(prompt, schema, timeout)
    elif provider == "anthropic":
        data = _ask_anthropic(prompt, schema, timeout)
    else:
        raise LlmError(f"Unknown LT_LLM_PROVIDER: {provider!r}. Use claude-cli, openai or anthropic.")
    missing = [k for k in schema.get("required", []) if k not in data]
    if missing:
        raise LlmError(f"The model answered without the required field(s) {missing}. Try a stronger model.")
    return data


def _post_json(url: str, headers: dict, body: dict, timeout: int) -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", **headers},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        raise LlmError(f"HTTP {exc.code} from {url}: {exc.read().decode(errors='replace')[:500]}") from exc
    except urllib.error.URLError as exc:
        raise LlmError(f"Could not reach {url}: {exc.reason}. Is the server running and the URL correct?") from exc


def _require_model() -> str:
    if not settings.llm_model:
        raise LlmError(f"Set LT_LLM_MODEL to the model name for the {settings.llm_provider} provider.")
    return settings.llm_model


def _extract_json(text: str) -> dict:
    try:
        return json.loads(text)
    except ValueError:
        pass
    try:  # models sometimes wrap the object in prose or a code fence
        return json.loads(text[text.index("{") : text.rindex("}") + 1])
    except ValueError as exc:
        raise LlmError(f"The model did not return valid JSON: {text[:300]!r}") from exc


def _ask_openai(prompt: str, schema: dict, timeout: int) -> dict:
    base = (settings.llm_base_url or OPENAI_DEFAULT_URL).rstrip("/")
    headers = {"Authorization": f"Bearer {settings.llm_api_key}"} if settings.llm_api_key else {}
    # Small local models follow a schema far better when it is also spelled out in the prompt.
    full_prompt = f"{prompt}\n\nReply with a single JSON object that matches this JSON Schema:\n{json.dumps(schema)}"
    body = {
        "model": _require_model(),
        "messages": [{"role": "user", "content": full_prompt}],
        "temperature": 0.2,
    }
    # Servers differ in what they enforce: try a strict schema, then plain JSON mode, then no constraint.
    formats = [
        {"type": "json_schema", "json_schema": {"name": "result", "schema": schema}},
        {"type": "json_object"},
        None,
    ]
    last_error: LlmError | None = None
    for fmt in formats:
        attempt = dict(body, **({"response_format": fmt} if fmt else {}))
        try:
            reply = _post_json(f"{base}/chat/completions", headers, attempt, timeout)
        except LlmError as exc:
            if "HTTP 400" in str(exc) or "HTTP 422" in str(exc):  # this response_format is not supported
                last_error = exc
                continue
            raise
        try:
            return _extract_json(reply["choices"][0]["message"]["content"])
        except (KeyError, IndexError, TypeError) as exc:
            raise LlmError(f"Unexpected reply from the server: {str(reply)[:300]}") from exc
    raise last_error  # type: ignore[misc]


def _ask_anthropic(prompt: str, schema: dict, timeout: int) -> dict:
    if not settings.llm_api_key:
        raise LlmError("Set LT_LLM_API_KEY to your Anthropic API key.")
    base = (settings.llm_base_url or ANTHROPIC_DEFAULT_URL).rstrip("/")
    body = {
        "model": _require_model(),
        "max_tokens": ANTHROPIC_MAX_TOKENS,
        "messages": [{"role": "user", "content": prompt}],
        # Forcing a tool call is the reliable way to get schema-shaped JSON back.
        "tools": [{"name": "report", "description": "Return the result.", "input_schema": schema}],
        "tool_choice": {"type": "tool", "name": "report"},
    }
    headers = {"x-api-key": settings.llm_api_key, "anthropic-version": "2023-06-01"}
    reply = _post_json(f"{base}/v1/messages", headers, body, timeout)
    for block in reply.get("content", []):
        if block.get("type") == "tool_use":
            return block["input"]
    raise LlmError(f"The Anthropic API returned no structured result: {str(reply)[:300]}")
