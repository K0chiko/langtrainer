# Running with a local model (no subscription, no cloud)

Mistake analysis and advice need a language model. Besides the Claude subscription, the app can talk to any server that speaks the OpenAI chat API, which includes all popular local runtimes. Then nothing leaves your computer at all: audio and text both stay local.

> Status: the OpenAI-compatible provider is covered by automated tests against a simulated server. It has not yet been verified against each runtime below on real hardware, so report anything that does not work.

## Choose a runtime

| Runtime | Good for | Server URL to use |
|---|---|---|
| [Ollama](https://ollama.com) | Simplest. Windows, macOS, Linux. | `http://localhost:11434/v1` |
| [LM Studio](https://lmstudio.ai) | A desktop app with a model browser. | `http://localhost:1234/v1` |
| [llama.cpp](https://github.com/ggml-org/llama.cpp) `llama-server` | Lightweight, full control. | `http://localhost:8080/v1` |

## Ollama, step by step

1. Install Ollama from https://ollama.com/download and start it (on Windows and macOS it runs in the background after install).
2. Download a model. Pull it once, it is stored on disk:

   ```bash
   ollama pull qwen2.5:7b
   ```

3. Check that it answers:

   ```bash
   ollama run qwen2.5:7b "Say hello"
   ```

4. Tell the app to use it. Create a file named `.env` in the folder where you start the app:

   ```
   LT_LLM_PROVIDER=openai
   LT_LLM_BASE_URL=http://localhost:11434/v1
   LT_LLM_MODEL=qwen2.5:7b
   LT_ANALYZE_BATCH_SIZE=15
   LT_LLM_TIMEOUT=1800
   ```

5. Start the app (`uv run langtrainer`) and process a conversation as usual.

For LM Studio, load a model, open the *Developer* tab, start the server, and use its URL and the model name it shows. For llama.cpp, start `llama-server -m model.gguf` and use `http://localhost:8080/v1`; the model name can be anything.

## Picking a model

- **Size matters a lot.** Finding real mistakes without inventing fake ones is hard. Models of about 7-8 billion parameters are the practical minimum; 14B and larger are noticeably more reliable. Expect a local model to be weaker than a large hosted one, and expect some false positives (you can dismiss them in the interface).
- **Memory.** A 7-8B model at 4-bit quantisation needs roughly 5-6 GB of free RAM or GPU memory, a 14B model about 10 GB. If the model does not fit in memory it will be very slow.
- **Language.** The explanations are written in your native language (Russian by default). Small models write weaker Russian than English. If explanations look poor, try a larger model.
- Good starting points on Ollama: `qwen2.5:7b`, `qwen2.5:14b`, `llama3.1:8b`. Any instruction-tuned model that follows JSON instructions can work.

## Settings that matter for local models

| Setting | Why |
|---|---|
| `LT_ANALYZE_BATCH_SIZE` | Utterances per request. The default (60) is tuned for large hosted models. Use 10-20 for small local models: shorter prompts, more reliable JSON. |
| `LT_LLM_TIMEOUT` | Seconds allowed per request. A CPU-only machine can need many minutes per batch. |
| Context window | Ollama's default context is small and it silently cuts off a prompt that does not fit. If results look incomplete, raise it: create a file `Modelfile` with `FROM qwen2.5:7b` and `PARAMETER num_ctx 8192`, run `ollama create qwen-ctx -f Modelfile`, and set `LT_LLM_MODEL=qwen-ctx`. |

## Troubleshooting

- *"Could not reach http://localhost:11434/v1/chat/completions"*: the server is not running or the URL is wrong.
- *"HTTP 404 ... model not found"*: `LT_LLM_MODEL` must match the name from `ollama list` exactly.
- *"did not return valid JSON"* or *"without the required field"*: the model is too small or the batch is too large. Lower `LT_ANALYZE_BATCH_SIZE` or use a bigger model.
- Analysis is very slow: use a smaller model, or check that it runs on the GPU (`ollama ps`).
- Whisper (speech recognition) is separate and already local; this guide only covers the text model.

## Hosted alternatives

The same `openai` provider works with hosted services: set `LT_LLM_BASE_URL` (for example `https://openrouter.ai/api/v1`; leave it empty for OpenAI itself), `LT_LLM_API_KEY` and `LT_LLM_MODEL`. For Anthropic's API use `LT_LLM_PROVIDER=anthropic` with `LT_LLM_API_KEY` and `LT_LLM_MODEL`. See the main README.
