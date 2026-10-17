from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Настройки читаются из переменных окружения LT_* или из файла .env."""

    model_config = SettingsConfigDict(env_prefix="LT_", env_file=".env", extra="ignore")

    # Куда класть аудио и (по умолчанию) файл SQLite. Не задана = приложение спросит папку при первом запуске
    # (см. storage.py). Можно указать папку на Synology или внешнем диске.
    data_dir: Path | None = None
    # SQLAlchemy URL. Пусто = SQLite в data_dir. Пример для Synology: postgresql+psycopg://user:pw@nas:5432/lt
    database_url: str = ""

    # Распознавание речи: "auto" (= faster-whisper), "faster-whisper" или "mlx" (только Mac, нужен ffmpeg)
    transcriber: str = "auto"
    # Многоязычная модель, чтобы тот же код работал и для русской речи в зеркальном режиме.
    # Для только английского можно взять "small.en" / "medium.en" (точнее).
    whisper_model: str = "small"

    # Языковая модель для разбора ошибок и советов:
    #   "claude-cli" (по подписке, без ключа), "openai" (любой OpenAI-совместимый сервер: OpenAI, OpenRouter,
    #   локальные Ollama / LM Studio / llama.cpp), "anthropic" (API-ключ Anthropic).
    llm_provider: str = "claude-cli"
    llm_model: str = ""  # для claude-cli пусто = модель по умолчанию; для остальных провайдеров обязательно
    llm_base_url: str = ""  # для openai: например http://localhost:11434/v1 (Ollama); пусто = api.openai.com
    llm_api_key: str = ""  # локальным серверам обычно не нужен
    llm_timeout: int = 600  # секунд на один запрос; локальным моделям на CPU может понадобиться больше
    analyze_batch_size: int = 60  # реплик на один запрос

    @property
    def db_url(self) -> str:
        return self.database_url or f"sqlite:///{(self.require_data_dir() / 'langtrainer.db').resolve()}"

    @property
    def audio_dir(self) -> Path:
        return self.require_data_dir() / "audio"

    def require_data_dir(self) -> Path:
        if self.data_dir is None:
            raise RuntimeError("The data folder has not been chosen yet.")
        return self.data_dir


settings = Settings()
