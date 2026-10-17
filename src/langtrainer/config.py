from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Настройки читаются из переменных окружения LT_* или из файла .env."""

    model_config = SettingsConfigDict(env_prefix="LT_", env_file=".env", extra="ignore")

    # Куда класть аудио и (по умолчанию) файл SQLite. Можно указать папку на Synology.
    data_dir: Path = Path("data")
    # SQLAlchemy URL. Пусто = SQLite в data_dir. Пример для Synology: postgresql+psycopg://user:pw@nas:5432/lt
    database_url: str = ""

    # Распознавание речи: "auto" (= faster-whisper), "faster-whisper" или "mlx" (только Mac, нужен ffmpeg)
    transcriber: str = "auto"
    # Многоязычная модель, чтобы тот же код работал и для русской речи в зеркальном режиме.
    # Для только английского можно взять "small.en" / "medium.en" (точнее).
    whisper_model: str = "small"

    # Анализатор ошибок. Сейчас реализован только "claude-cli" (по подписке).
    analyzer: str = "claude-cli"
    claude_model: str = ""  # пусто = модель по умолчанию в CLI
    analyze_batch_size: int = 60  # реплик на один запрос

    @property
    def db_url(self) -> str:
        return self.database_url or f"sqlite:///{(self.data_dir / 'langtrainer.db').resolve()}"

    @property
    def audio_dir(self) -> Path:
        return self.data_dir / "audio"


settings = Settings()
